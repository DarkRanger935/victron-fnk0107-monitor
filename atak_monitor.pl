#!/usr/bin/env perl
use strict;
use warnings;
use IO::Socket::INET;
use IO::Socket::UNIX;
use IO::Socket::SSL;
use XML::Simple;
use Geo::Coordinates::MGRS;

# --- CONFIGURATION ---
my $TAK_SERVER_IP = '127.0.0.1';
my $TAK_PORT      = 8089;
my $IPC_SOCKET    = '/run/victron-monitor/victron_alerts.sock';

# Base path pointing to your docker-managed local directory
my $CERT_DIR = '/TAKSERVER/takserver-docker-5.6-RELEASE-57/tak/certs/files';

# Target certificate parameters
my $SSL_CERT = "$CERT_DIR/admin.pem";
my $SSL_KEY  = "$CERT_DIR/admin.key";
my $SSL_CA   = "$CERT_DIR/ca.pem";

# Initialize secure TLS socket connection to the local TAK Server container
my $socket = IO::Socket::SSL->new(
    PeerHost        => $TAK_SERVER_IP,
    PeerPort        => $TAK_PORT,
    Proto           => 'tcp',
    SSL_cert_file   => $SSL_CERT,
    SSL_key_file    => $SSL_KEY,
    SSL_ca_file     => $SSL_CA,
    SSL_verify_mode => SSL_VERIFY_PEER,
) or die "Failed to connect to TAK Server TLS stream: " . IO::Socket::SSL::errstr();
print "Successfully established connection to TAK Server on port $TAK_PORT [mTLS]\n";
my $xml_parser = XML::Simple->new(ForceArray => [ 'emergency', 'casevac' ]);

# Keep connection active and ingest live streaming server packets
while (my $line = <$socket>) {
    # CoT streams over TCP typically append explicit closing tags or use raw line breaks
    if ($line =~ /<event/ && $line =~ /<\/event>/) {
        my ($xml_payload) = $line =~ /(<event.*<\/event>)/s;
        next unless $xml_payload;

        eval {
            my $data = $xml_parser->XMLin($xml_payload);

            my $has_emergency = exists $data->{detail}->{emergency};
            my $has_casevac   = exists $data->{detail}->{casevac};

            if ($has_emergency || $has_casevac) {
                my $callsign = $data->{detail}->{uid}->{callsign} || "UNKNOWN_CALLSIGN";
                my $lat      = $data->{point}->{lat};
                my $lon      = $data->{point}->{lon};

                my $mgrs_position = "UNKNOWN_COORD";
                if (defined $lat && $lat =~ /^-?\d+\.?\d*$/ && defined $lon) {
                    eval { $mgrs_position = latlon_to_mgrs($lat, $lon); };
                }

                my $alert_type = "EMERGENCY ALERT";
                my $is_cleared = "false";

                if ($has_casevac) {
                    $alert_type = "CASEVAC/MEDEVAC REQUEST";
                } elsif ($has_emergency) {
                    my $em_type = $data->{detail}->{emergency}->[0]->{type};
                    my $cancel_status = $data->{detail}->{emergency}->[0]->{cancel};

                    if (defined $cancel_status && $cancel_status eq 'true') {
                        $is_cleared = "true";
                        $alert_type = uc($em_type || "GENERAL EMERGENCY") . " CLEARED";
                    } else {
                        $alert_type = uc($em_type || "GENERAL EMERGENCY");
                    }
                }

                # Construct raw payload string: "STATUS|TYPE|CALLSIGN|MGRS"
                my $ipc_payload = sprintf("%s|%s|%s|%s\n", $is_cleared, $alert_type, $callsign, $mgrs_position);

                # Forward cleanly to the python engine socket path
                if (-S $IPC_SOCKET) {
                    my $uds_client = IO::Socket::UNIX->new(
                        Peer => $IPC_SOCKET,
                        Type => SOCK_STREAM,
                    );
                    if ($uds_client) {
                        print $uds_client $ipc_payload;
                        close($uds_client);
                        print "[ALARM EVENT] Sent to display layer: $ipc_payload";
                    }
                }
            }
        };
    }
}

close($socket);
