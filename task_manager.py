#!/usr/bin/env python3
import os
import subprocess
import sys
import threading
import time
import api_oled
import api_systemInfo
import api_victron
from api_json import ConfigManager
from api_expansion import Expansion
import atexit
import signal

API_MODULE_REFERENCES = (api_oled, api_systemInfo, api_victron)

class TaskManager:
    """
    A class to manage and execute tasks using external ConfigManager
    """
    
    def __init__(self, config_file="app_config.json"):
        """
        Initialize the TaskManager
        
        Args:
            config_file (str): Path to the configuration file
        """
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(self.script_dir, config_file)
        self.python_executable = "/usr/bin/python3"
        self.state_lock = threading.RLock()
        self.config_manager = ConfigManager(self.config_path)
        self.running_processes = {}  # Store running processes
        self.monitor_thread = None
        self.monitoring = False
        self.shutting_down = False
        self.expansion = Expansion()
        led_config = self.config_manager.get_section('LED')
        fan_config = self.config_manager.get_section('Fan')
        led_config = led_config if isinstance(led_config, dict) else {}
        fan_config = fan_config if isinstance(fan_config, dict) else {}
        if not led_config.get('is_run_on_startup', True):
            self.send_led_mode_to_expansion(led_config.get('mode', 0))
        if not fan_config.get('is_run_on_startup', True):
            self.send_fan_mode_to_expansion(fan_config.get('mode', 0))
        
        atexit.register(self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)


    def send_led_mode_to_expansion(self, led_mode):
        """Send LED mode to expansion board"""
        if led_mode == 0:
            self.expansion.set_led_mode(4)                 
        elif led_mode == 1:
            self.expansion.set_led_mode(3)
        elif led_mode == 2:
            self.expansion.set_led_mode(2)
        elif led_mode == 3:
            self.expansion.set_led_mode(1)
        elif led_mode == 5:
            self.expansion.set_led_mode(0)
    
    def send_fan_mode_to_expansion(self, mode):
        """Send fan mode to expansion board"""
        if self.expansion.get_board_type() == "FNK0100":
            if mode == 0:
                self.expansion.set_fan_mode(2)  
            elif mode == 1:
                self.expansion.set_fan_mode(1)
            elif mode == 3:
                self.expansion.set_fan_mode(0)
        elif self.expansion.get_board_type() == "FNK0107":
            if mode == 0:
                self.expansion.set_fan_mode(2)  
            elif mode == 1:
                self.expansion.set_fan_mode(3)
            elif mode == 2:
                self.expansion.set_fan_mode(1)
            elif mode == 4:
                self.expansion.set_fan_mode(0)

    def handle_signal(self, signum=None, frame=None):
        """Handle signals"""
        with self.state_lock:
            if self.shutting_down:
                return
            self.shutting_down = True
        print("Received signal:", signum)
        self.stop_monitoring()

    def _start_managed_task(self, task):
        task_path = task["path"]
        with self.state_lock:
            existing_proc = self.running_processes.get(task_path)
            if existing_proc is not None and existing_proc.poll() is None:
                return
            if task_path in self.running_processes:
                self.running_processes.pop(task_path, None)
            self.running_processes[task_path] = None

        proc = self.start_task(task)

        with self.state_lock:
            if task_path not in self.running_processes:
                if proc and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                return

            if proc:
                self.running_processes[task_path] = proc
            else:
                self.running_processes.pop(task_path, None)

    def get_enabled_tasks(self):
        """
        Get tasks that are enabled for startup
        
        Returns:
            list: Tasks with is_run_on_startup set to True
        """
        # Get all tasks from config file
        tasks = []
        self.config_manager.load_config()
        
        # Get task configs for each module
        led_config = self.config_manager.get_section('LED')
        fan_config = self.config_manager.get_section('Fan')
        oled_config = self.config_manager.get_section('OLED')
        
        # Add LED task
        if led_config and 'task_name' in led_config:
            tasks.append({
                'path': led_config['task_name'],
                'is_run_on_startup': led_config.get('is_run_on_startup', True)
            })
        
        # Add Fan task
        if fan_config and 'task_name' in fan_config:
            tasks.append({
                'path': fan_config['task_name'],
                'is_run_on_startup': fan_config.get('is_run_on_startup', True)
            })
        
        # Add OLED task
        if oled_config and 'task_name' in oled_config:
            tasks.append({
                'path': oled_config['task_name'],
                'is_run_on_startup': oled_config.get('is_run_on_startup', True)
            })
        
        # Return enabled tasks
        return [task for task in tasks if task.get("is_run_on_startup", True)]

    def get_disabled_tasks(self):
        """
        Get tasks that are disabled for startup
        
        Returns:
            list: Tasks with is_run_on_startup set to False
        """
        # Get all tasks from config file
        tasks = []
        self.config_manager.load_config()
        
        # Get task configs for each module
        led_config = self.config_manager.get_section('LED')
        fan_config = self.config_manager.get_section('Fan')
        oled_config = self.config_manager.get_section('OLED')
        
        # Add LED task
        if led_config and 'task_name' in led_config:
            tasks.append({
                'path': led_config['task_name'],
                'is_run_on_startup': led_config.get('is_run_on_startup', False)
            })
        
        # Add Fan task
        if fan_config and 'task_name' in fan_config:
            tasks.append({
                'path': fan_config['task_name'],
                'is_run_on_startup': fan_config.get('is_run_on_startup', False)
            })
        
        # Add OLED task
        if oled_config and 'task_name' in oled_config:
            tasks.append({
                'path': oled_config['task_name'],
                'is_run_on_startup': oled_config.get('is_run_on_startup', False)
            })
        
        # Return disabled tasks
        return [task for task in tasks if not task.get("is_run_on_startup", False)]

    def list_tasks(self):
        """
        Print all tasks with their status
        """
        tasks = []
        self.config_manager.load_config()
        
        # Get task configs for each module
        led_config = self.config_manager.get_section('LED')
        fan_config = self.config_manager.get_section('Fan')
        oled_config = self.config_manager.get_section('OLED')
        
        # Add LED task
        if led_config and 'task_name' in led_config:
            tasks.append({
                'path': led_config['task_name'],
                'is_run_on_startup': led_config.get('is_run_on_startup', False)
            })
        
        # Add Fan task
        if fan_config and 'task_name' in fan_config:
            tasks.append({
                'path': fan_config['task_name'],
                'is_run_on_startup': fan_config.get('is_run_on_startup', False)
            })
        
        # Add OLED task
        if oled_config and 'task_name' in oled_config:
            tasks.append({
                'path': oled_config['task_name'],
                'is_run_on_startup': oled_config.get('is_run_on_startup', False)
            })
        
        if not tasks:
            print("No tasks configured")
            return
        
        print("Configured tasks:")
        for i, task in enumerate(tasks, 1):
            status = "ON" if task["is_run_on_startup"] else "OFF"
            print(f"  {i}. {task['path']} [{status}]")

    def start_task(self, task):
        """
        Start a single task
        
        Args:
            task (dict): Task configuration
            
        Returns:
            subprocess.Popen or None: Process object if started successfully
        """
        task_path = os.path.join(self.script_dir, task["path"])
        if os.path.exists(task_path):
            print(f"Starting task: {task['path']}")
            proc = subprocess.Popen([self.python_executable, task_path], cwd=self.script_dir)
            return proc
        else:
            print(f"Warning: Task file {task['path']} not found")
            return None

    def stop_task(self, task_path):
        """
        Stop a running task
        
        Args:
            task_path (str): Path to the task file
        """
        with self.state_lock:
            proc = self.running_processes.get(task_path)
            if proc is None and task_path in self.running_processes:
                self.running_processes.pop(task_path, None)
                return

        if proc:
            if proc.poll() is None:  # Check if process is still running
                proc.terminate()
                try:
                    proc.wait(timeout=2)  # Wait up to 2 seconds
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()  # Wait for force kill to complete
            with self.state_lock:
                self.running_processes.pop(task_path, None)
            print(f"Stopped task: {task_path}")

    def execute_enabled_tasks(self):
        """
        Execute all tasks that are enabled (is_run_on_startup = True)
        """
        # Get the list of enabled tasks
        enabled_tasks = self.get_enabled_tasks()
        
        if not enabled_tasks:
            print("No tasks enabled for execution")
            return
            
        # Start all enabled tasks as separate processes
        for task in enabled_tasks:
            self._start_managed_task(task)

    def _monitor_tasks(self):
        """
        Monitor thread function that checks for task status changes every 0.3 seconds
        """
        # Save previous config status
        last_enabled_tasks = set()
        last_disabled_tasks = set()
        
        while self.monitoring:
            try:
                # Get current enabled and disabled tasks
                enabled_tasks = self.get_enabled_tasks()
                disabled_tasks = self.get_disabled_tasks()
                
                # Extract task paths for comparison
                current_enabled_paths = set(task['path'] for task in enabled_tasks)
                current_disabled_paths = set(task['path'] for task in disabled_tasks)
                
                # Check if config has changed
                if (current_enabled_paths != last_enabled_tasks or 
                    current_disabled_paths != last_disabled_tasks):
                    
                    # Print current config status
                    print(f"Current configuration - Enabled tasks: {list(current_enabled_paths)}")
                    print(f"Current configuration - Disabled tasks: {list(current_disabled_paths)}")
                    
                    # Update saved status
                    last_enabled_tasks = current_enabled_paths
                    last_disabled_tasks = current_disabled_paths
                
                # Start newly enabled tasks
                for task in enabled_tasks:
                    self._start_managed_task(task)
                
                # Stop disabled tasks
                for task in disabled_tasks:
                    task_path = task["path"]
                    with self.state_lock:
                        should_stop = task_path in self.running_processes
                    if should_stop:
                        self.stop_task(task_path)
                
                time.sleep(0.3)  # Check every 0.3 seconds
                
            except Exception as e:
                print(f"Error in monitor thread: {e}")
                time.sleep(0.3)
                
    def start_monitoring(self):
        """
        Start the monitoring thread
        """
        with self.state_lock:
            if self.monitoring:
                return
            self.monitoring = True
            self.monitor_thread = threading.Thread(target=self._monitor_tasks, daemon=True)
            self.monitor_thread.start()
        print("Task monitoring started")

    def stop_monitoring(self):
        """
        Stop the monitoring thread and all running tasks
        """
        with self.state_lock:
            self.monitoring = False
            monitor_thread = self.monitor_thread
        if monitor_thread and monitor_thread.is_alive():
            monitor_thread.join()
        
        # Stop all running tasks
        with self.state_lock:
            task_paths = list(self.running_processes.keys())
        for task_path in task_paths:
            self.stop_task(task_path)

        self.config_manager.load_config()
        led_config = self.config_manager.get_section('LED')
        fan_config = self.config_manager.get_section('Fan')
        led_config = led_config if isinstance(led_config, dict) else {}
        fan_config = fan_config if isinstance(fan_config, dict) else {}

        self.send_led_mode_to_expansion(led_config.get('mode', 0))
        self.send_fan_mode_to_expansion(fan_config.get('mode', 0))
        print("Task monitoring stopped")


    def set_task_status(self, task_path, is_run_on_startup):
        """
        Update the startup status of a task
        
        Args:
            task_path (str): Path to the task file
            is_run_on_startup (bool): New startup status
            
        Returns:
            bool: True if task was updated, False if it didn't exist
        """
        # Find and update the corresponding task status
        config_updated = False
        self.config_manager.load_config()
        
        # Check LED config
        led_config = self.config_manager.get_section('LED')
        if led_config and led_config.get('task_name') == task_path:
            self.config_manager.set_value('LED', 'is_run_on_startup', is_run_on_startup)
            config_updated = True
        
        # Check Fan config
        fan_config = self.config_manager.get_section('Fan')
        if fan_config and fan_config.get('task_name') == task_path:
            self.config_manager.set_value('Fan', 'is_run_on_startup', is_run_on_startup)
            config_updated = True
        
        # Check OLED config
        oled_config = self.config_manager.get_section('OLED')
        if oled_config and oled_config.get('task_name') == task_path:
            self.config_manager.set_value('OLED', 'is_run_on_startup', is_run_on_startup)
            config_updated = True
        
        if config_updated:
            self.config_manager.save_config()
            status = "enabled" if is_run_on_startup else "disabled"
            print(f"Task {task_path} {status} for startup")
            return True
        else:
            print(f"Task {task_path} not found in config")
            return False


# Example usage
if __name__ == "__main__":
    # Create an instance of the manager
    manager = TaskManager()
    
    print("\n=== Starting Enabled Tasks ===")
    # Start tasks enabled in config file
    manager.execute_enabled_tasks()
    
    print("\n=== Starting Task Monitoring ===")
    # Start monitoring task status changes
    manager.start_monitoring()
    
    # Keep program running until termination signal received
    try:
        # Wait for user interrupt signal (Ctrl+C)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nReceived interrupt signal, shutting down...")
    finally:
        manager.stop_monitoring()