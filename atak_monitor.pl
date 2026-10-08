#!/usr/bin/env perl
use strict;
use warnings;
use IO::Socket::INET;
use IO::Socket::SSL; 
use IO::Socket::UNIX;
use XML::Simple;
use Geo::Coordinates::UTM; 

# --- CONFIGURATION ---
my $TAK_SERVER_IP = 'takserver'; 
my $TAK_PORT      = 8089;
my $IPC_SOCKET    = '/dev/shm/victron_alerts.sock';

# Explicit file directory paths matching your Docker deployment structure
my $CERT_DIR = '/TAKSERVER/takserver-docker-5.6-RELEASE-57/tak/certs/files';

# Target administrative certificate file pointers
my $SSL_CERT = "$CERT_DIR/admin.pem";
my $SSL_KEY  = "$CERT_DIR/admin.key";
my $SSL_CA   = "$CERT_DIR/ca.pem";
# ---------------------

print "Initializing ATAK mTLS Monitor Service (UTM Engine)...\n";

# Initialize secure TLS socket connection to the local TAK Server container
my $socket = IO::Socket::SSL->new(
    PeerHost        => $TAK_SERVER_IP,
    PeerPort        => $TAK_PORT,
    Proto           => 'tcp',
    SSL_cert_file   => $SSL_CERT,
    SSL_key_file    => $SSL_KEY,
    SSL_ca_file     => $SSL_CA,
    SSL_verify_mode => 1,
    SSL_passwd_cb   => sub { return "atakatak" },
) or die "Failed to connect to TAK Server TLS stream: " . IO::Socket::SSL::errstr();

print "Successfully established connection to TAK Server on port $TAK_PORT [mTLS]\n";

my $xml_parser = XML::Simple->new(ForceArray => [ 'casevac' ]);

# Keep connection active and ingest live streaming server packets
while (my $line = <$socket>) {
    #print "RAW STREAM: $line\n";
    if ($line =~ /<event/ && $line =~ /<\/event>/) {
        my ($xml_payload) = $line =~ /(<event.*<\/event>)/s;
        next unless $xml_payload;

        eval {
            my $data = $xml_parser->XMLin($xml_payload);
            
            my $event_type    = $data->{type} || "";
            my $has_emergency = exists $data->{detail}->{emergency};
            my $has_casevac   = exists $data->{detail}->{casevac};

            if ($has_emergency || $has_casevac) {
                my $lat = $data->{point}->{lat};
                my $lon = $data->{point}->{lon};
                
                my $mgrs_position = "UNKNOWN_COORD";
                if (defined $lat && $lat =~ /^-?\d+\.?\d*$/ && defined $lon) {
                    eval { 
                        $mgrs_position = latlon_to_mgrs('WGS-84', $lat, $lon); 
                    };
                }

                # --- MULTI-TIER CALLSIGN LOOKUP ---
                my $callsign = undef;

                if (exists $data->{detail}->{contact} && ref($data->{detail}->{contact}) eq 'HASH') {
                    $callsign = $data->{detail}->{contact}->{callsign};
                }

                if (!defined $callsign && exists $data->{detail}->{uid} && ref($data->{detail}->{uid}) eq 'HASH') {
                    $callsign = $data->{detail}->{uid}->{callsign};
                }

                if (!defined $callsign && exists $data->{detail}->{emergency}) {
                    my $em_node = $data->{detail}->{emergency};
                    if (ref($em_node) eq '') {
                        $callsign = $em_node;
                    } elsif (ref($em_node) eq 'HASH' && exists $em_node->{content}) {
                        $callsign = $em_node->{content};
                    }
                }

                $callsign ||= "UNKNOWN_CALLSIGN";

                # FIXED: Strip any trailing "-Alert" or "-ALERT" variations 
                # so the base callsign matches perfectly across activations and cancellations
                $callsign =~ s/-Alert$//i;
                # ----------------------------------

                my $alert_type = "EMERGENCY ALERT";
                my $is_cleared = "false";

                if ($has_casevac) {
                    $alert_type = "CASEVAC/MEDEVAC REQUEST";
                } elsif ($has_emergency) {
                    my $em_node = $data->{detail}->{emergency};
                    my $em_type = ref($em_node) eq 'HASH' ? $em_node->{type} : undef;
                    
                    # FIXED: Parse both standard cancel attribute and the native 'b-a-o-can' type signature
                    my $cancel_attr = ref($em_node) eq 'HASH' ? ($em_node->{cancel} || $em_node->{cancel_status}) : 'false';
                    
                    $em_type ||= "IN CONTACT";

                    if ((defined $cancel_attr && $cancel_attr eq 'true') || $event_type eq 'b-a-o-can') {
                        $is_cleared = "true";
                        $alert_type = uc($em_type) . " CLEARED";
                    } else {
                        $alert_type = uc($em_type);
                    }
                }

                # Construct raw payload string: "STATUS|TYPE|CALLSIGN|MGRS"
                my $ipc_payload = sprintf("%s|%s|%s|%s\n", $is_cleared, $alert_type, $callsign, $mgrs_position);

                # Forward cleanly to the python engine socket path
                if (-S $IPC_SOCKET) {
                    my $uds_client = IO::Socket::UNIX->new(
                        Peer    => $IPC_SOCKET,
                        Type    => SOCK_STREAM,
                        Timeout => 1,
                    );
                    if ($uds_client) {
                        print $uds_client $ipc_payload;
                        close($uds_client);
                        print "[ALARM EVENT] Sent to display layer: $ipc_payload";
                    }
                }
            }
        };
        if ($@) {
            warn "Error parsing CoT stream: $@\n" if $^W;
        }
    }
}

close($socket);
