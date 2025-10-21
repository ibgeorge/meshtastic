import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import serial.tools.list_ports
import meshtastic
import meshtastic.serial_interface
import meshtastic.channel_pb2
import threading
import time
from pubsub import pub
import queue

class MeshtasticGUI(tk.Tk):
    """
    The main application window for the Meshtastic GUI tool.
    """
    def __init__(self):
        super().__init__()

        # --- Window Setup ---
        self.title("Meshtastic GUI Tool")
        self.geometry("1000x600")

        # --- Connection State ---
        self.interface = None
        self.is_connected = False
        self._after_id_nodes = None
        self._after_id_queue = None
        self.packet_queue = queue.Queue()

        # --- Globals for ACK handling ---
        self.ack_received_event = threading.Event()
        self.ack_response_status = "UNKNOWN"
        self.acks_lock = threading.Lock()
        self.waiting_for_ack_from = None

        # --- Filter State ---
        self.filter_vars = {
            "ADMIN_APP": tk.BooleanVar(value=True),
            "POSITION_APP": tk.BooleanVar(value=True),
            "TELEMETRY_APP": tk.BooleanVar(value=True),
            "NODEINFO_APP": tk.BooleanVar(value=True),
            "ROUTING_APP": tk.BooleanVar(value=False), # Hide ACKs by default
        }

        # --- Style Configuration ---
        self.style = ttk.Style(self)
        self.style.theme_use('clam')

        # --- Main Layout Frames ---
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.top_frame = ttk.Frame(self, padding="5")
        self.main_frame = ttk.Frame(self, padding="5")
        self.status_frame = ttk.Frame(self, padding="2", relief="groove")
        self.top_frame.grid(row=0, column=0, sticky="ew")
        self.main_frame.grid(row=1, column=0, sticky="nsew")
        self.status_frame.grid(row=2, column=0, sticky="ew")

        # --- Populate the Frames ---
        self.create_top_widgets()
        self.create_main_widgets()
        self.create_status_bar()

        # --- Handle Window Closing ---
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_top_widgets(self):
        """Creates the connection controls at the top of the window."""
        lbl_port = ttk.Label(self.top_frame, text="COM Port:")
        self.port_combobox = ttk.Combobox(self.top_frame, width=40, state="readonly")
        self.refresh_button = ttk.Button(self.top_frame, text="Refresh", command=self.refresh_com_ports)
        self.connect_button = ttk.Button(self.top_frame, text="Connect", command=self.toggle_connection)
        
        lbl_port.pack(side="left", padx=(0, 5))
        self.port_combobox.pack(side="left", padx=5)
        self.refresh_button.pack(side="left", padx=5)
        self.connect_button.pack(side="left", padx=5)

        self.refresh_com_ports()

    def refresh_com_ports(self):
        """Scans for available serial ports and updates the combobox."""
        ports = serial.tools.list_ports.comports()
        self.port_map = {f"{p.device} - {p.description}": p.device for p in ports}
        self.port_combobox['values'] = list(self.port_map.keys())
        if self.port_map:
            self.port_combobox.current(0)

    def create_main_widgets(self):
        """Creates the main content area for displaying nodes and messages."""
        paned_window = ttk.PanedWindow(self.main_frame, orient="horizontal")
        paned_window.pack(fill="both", expand=True)

        # --- Node List Treeview ---
        node_frame = ttk.Labelframe(paned_window, text="Nodes", padding="5")
        node_frame.grid_rowconfigure(0, weight=1)
        node_frame.grid_columnconfigure(0, weight=1)

        cols = ('name', 'id', 'snr', 'last_heard')
        self.node_tree = ttk.Treeview(node_frame, columns=cols, show='headings')
        self.node_tree.grid(row=0, column=0, sticky='nsew')

        self.node_tree.heading('name', text='Name')
        self.node_tree.heading('id', text='Node ID')
        self.node_tree.heading('snr', text='SNR')
        self.node_tree.heading('last_heard', text='Last Heard')
        self.node_tree.column('name', width=120)
        self.node_tree.column('id', width=100)
        self.node_tree.column('snr', width=50, anchor='center')
        self.node_tree.column('last_heard', width=80, anchor='center')

        # Bind the double-click event
        self.node_tree.bind("<Double-1>", self.on_node_double_click)

        scrollbar_nodes = ttk.Scrollbar(node_frame, orient="vertical", command=self.node_tree.yview)
        self.node_tree.configure(yscroll=scrollbar_nodes.set)
        scrollbar_nodes.grid(row=0, column=1, sticky='ns')
        
        # --- Message & Log Text Area ---
        message_frame = ttk.Labelframe(paned_window, text="Messages & Log", padding="5")
        message_frame.grid_rowconfigure(1, weight=1) 
        message_frame.grid_columnconfigure(0, weight=1)
        
        # --- Filter Controls ---
        filter_frame = ttk.Frame(message_frame)
        filter_frame.grid(row=0, column=0, sticky='ew', pady=(0, 5))
        lbl_filter = ttk.Label(filter_frame, text="Show Packets:")
        lbl_filter.pack(side="left")

        for key, var in self.filter_vars.items():
            cb = ttk.Checkbutton(filter_frame, text=key.replace('_APP',''), variable=var)
            cb.pack(side="left", padx=3)

        self.message_text = scrolledtext.ScrolledText(message_frame, state='disabled', wrap=tk.WORD, bg="#f0f0f0")
        self.message_text.grid(row=1, column=0, sticky='nsew')

        # --- Message Sending Controls ---
        send_frame = ttk.Frame(message_frame, padding=(0, 5))
        send_frame.grid(row=2, column=0, sticky='ew')
        send_frame.grid_columnconfigure(0, weight=1)

        self.message_entry = ttk.Entry(send_frame)
        self.message_entry.grid(row=0, column=0, sticky='ew', padx=(0, 5))
        
        self.channel_combobox = ttk.Combobox(send_frame, width=15, state="disabled")
        self.channel_combobox.grid(row=0, column=1, sticky='e', padx=5)

        self.send_button = ttk.Button(send_frame, text="Send", command=self.send_message)
        self.send_button.grid(row=0, column=2, sticky='e')
        
        self.message_text.tag_config('info', foreground='blue')
        self.message_text.tag_config('error', foreground='red')
        self.message_text.tag_config('message', foreground='black')
        self.message_text.tag_config('meta', foreground='gray')
        self.message_text.tag_config('success', foreground='green')
        self.message_text.tag_config('warning', foreground='#E4A81E')

        paned_window.add(node_frame, weight=2)
        paned_window.add(message_frame, weight=3)

    def create_status_bar(self):
        """Creates the status bar at the bottom of the window."""
        self.status_label = ttk.Label(self.status_frame, text="Status: Disconnected", anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True, padx=5)

    def toggle_connection(self):
        """Starts a new thread to either connect or disconnect."""
        if self.is_connected:
            threading.Thread(target=self.disconnect_from_device, daemon=True).start()
        else:
            threading.Thread(target=self.connect_to_device, daemon=True).start()

    def connect_to_device(self):
        """Handles the device connection logic."""
        selected_port_display = self.port_combobox.get()
        if not selected_port_display:
            self.after(0, lambda: messagebox.showerror("Connection Error", "No COM port selected."))
            return

        port_device = self.port_map.get(selected_port_display)
        self.after(0, self.set_ui_connecting)
        
        try:
            self.interface = meshtastic.serial_interface.SerialInterface(devPath=port_device)
            # Subscribe immediately to start filling the queue
            pub.subscribe(self.on_packet_received, "meshtastic.receive")
            time.sleep(2) # Give time for initial packets to arrive
            self.is_connected = True
            self.after(0, self.set_ui_connected)
        except Exception as e:
            self.is_connected = False
            self.interface = None
            self.after(0, lambda err=e: self.set_ui_disconnected(error=err))

    def disconnect_from_device(self):
        """Handles the device disconnection logic."""
        if self.interface:
            self.interface.close()
        self.interface = None
        self.is_connected = False
        self.after(0, self.set_ui_disconnected)

    def set_ui_connecting(self):
        """Updates the UI to a 'connecting' state."""
        self.status_label.config(text="Status: Connecting...")
        self.connect_button.config(text="Connecting...", state="disabled")
        self.port_combobox.config(state="disabled")
        self.refresh_button.config(state="disabled")
        self.send_button.config(state="disabled")

    def set_ui_connected(self):
        """Updates the UI to a 'connected' state."""
        try:
            owner_name = self.interface.myInfo.long_name
            self.status_label.config(text=f"Status: Connected to {owner_name}")
        except (AttributeError, KeyError):
            self.status_label.config(text="Status: Connected")
        
        self.log_to_message_window("Successfully connected to device.", "info")
        self.connect_button.config(text="Disconnect", state="normal")
        self.send_button.config(state="normal")
        self.channel_combobox.config(state="readonly")
        
        self.update_channel_list()
        self.update_node_list()
        self.process_queue() # Start the queue processor loop

    def set_ui_disconnected(self, error=None):
        """Updates the UI to a 'disconnected' state."""
        if error:
            messagebox.showerror("Connection Failed", f"Could not connect to the device.\n\nError: {error}")
            self.status_label.config(text="Status: Connection Failed")
            self.log_to_message_window(f"Connection failed: {error}", "error")
        else:
            self.status_label.config(text="Status: Disconnected")
            self.log_to_message_window("Disconnected.", "info")
        
        if self._after_id_nodes:
            self.after_cancel(self._after_id_nodes)
            self._after_id_nodes = None
        if self._after_id_queue:
            self.after_cancel(self._after_id_queue)
            self._after_id_queue = None
            
        while not self.packet_queue.empty():
            try:
                self.packet_queue.get_nowait()
            except queue.Empty:
                break

        for i in self.node_tree.get_children():
            self.node_tree.delete(i)

        self.connect_button.config(text="Connect", state="normal")
        self.port_combobox.config(state="readonly")
        self.refresh_button.config(state="normal")
        self.send_button.config(state="disabled")
        self.channel_combobox.config(state="disabled", values=[])
        self.refresh_com_ports()

    def on_packet_received(self, packet, interface):
        """Callback from Meshtastic library. Puts packets into a thread-safe queue."""
        # First, check if this is an ACK we are waiting for
        with self.acks_lock:
            if self.waiting_for_ack_from and packet.get('fromId') == self.waiting_for_ack_from and packet.get('decoded', {}).get('portnum') == 'ROUTING_APP':
                routing = packet.get('decoded', {}).get('routing', {})
                error = routing.get('errorReason', 'UNKNOWN_RESPONSE')
                self.ack_response_status = error
                self.ack_received_event.set()
                return # It's an ACK for us, don't queue it for display

        # If it's not an ACK for an outstanding DM, queue it for display
        self.packet_queue.put(packet)
        
    def process_queue(self):
        """Processes packets from the queue and updates the UI."""
        try:
            while not self.packet_queue.empty():
                packet = self.packet_queue.get_nowait()
                self.update_message_window(packet)
        except queue.Empty:
            pass
        finally:
            self._after_id_queue = self.after(100, self.process_queue)
        
    def update_node_list(self):
        """Periodically updates the node list in the Treeview, preserving selection."""
        if not self.is_connected or not self.interface:
            return
        
        selected_id = None
        if self.node_tree.selection():
            selected_node = self.node_tree.item(self.node_tree.selection()[0])
            if selected_node['values']:
                selected_id = selected_node['values'][1]

        for i in self.node_tree.get_children():
            self.node_tree.delete(i)
            
        nodes = self.interface.nodes.values()
        sorted_nodes = sorted(nodes, key=lambda n: n.get('lastHeard', 0), reverse=True)
        
        item_to_reselect = None
        for node in sorted_nodes:
            user = node.get('user', {})
            node_id = user.get('id', 'N/A')
            long_name = user.get('longName', 'N/A')
            snr = node.get('snr', 'N/A')
            last_heard_ts = node.get('lastHeard')
            
            last_heard_str = "Never"
            if last_heard_ts:
                last_heard_str = time.strftime('%H:%M:%S', time.localtime(last_heard_ts))
            
            item_id = self.node_tree.insert('', 'end', values=(long_name, node_id, snr, last_heard_str))
            
            if node_id == selected_id:
                item_to_reselect = item_id

        if item_to_reselect:
            self.node_tree.selection_set(item_to_reselect)
            self.node_tree.focus(item_to_reselect)

        self._after_id_nodes = self.after(5000, self.update_node_list)

    def update_channel_list(self):
        """Populates the channel combobox."""
        if not self.is_connected or not self.interface.localNode or not hasattr(self.interface.localNode, 'channels'):
            return
        
        self.channel_map = {ch.settings.name: i for i, ch in enumerate(self.interface.localNode.channels)}
        channel_names = list(self.channel_map.keys())
        self.channel_combobox['values'] = channel_names

        for i, ch in enumerate(self.interface.localNode.channels):
            if ch.role == meshtastic.channel_pb2.Channel.Role.PRIMARY:
                self.channel_combobox.current(i)
                break

    def update_message_window(self, packet):
        """Appends a formatted message to the message text widget."""
        decoded = packet.get('decoded', {})
        portnum = decoded.get('portnum', 'UNKNOWN')

        if portnum in self.filter_vars and not self.filter_vars[portnum].get():
            return

        from_node_id = packet.get('fromId', 'N/A')
        
        from_str = from_node_id
        if self.interface and from_node_id in self.interface.nodes:
            node_info = self.interface.nodes[from_node_id]
            user = node_info.get('user')
            if user:
                long_name = user.get('longName')
                short_name = user.get('shortName')
                if long_name and long_name != "N/A":
                    from_str = f"{long_name} ({from_node_id})"
                elif short_name and short_name != "N/A":
                     from_str = f"{short_name} ({from_node_id})"

        log_entry = f"[{time.strftime('%H:%M:%S')}] From: {from_str}\n"
        tag = "meta"
        
        if portnum == 'TEXT_MESSAGE_APP':
            text = decoded.get('text', 'Empty message')
            log_entry += f"  Message: {text}\n"
            tag = "message"
        elif portnum == 'POSITION_APP':
            pos = decoded.get('position', {})
            lat = pos.get('latitude', 'N/A')
            lon = pos.get('longitude', 'N/A')
            log_entry += f"  Position: Lat={lat:.5f}, Lon={lon:.5f}\n"
        else:
            log_entry += f"  Packet Type: {portnum}\n"
            log_entry += f"  Data: {decoded}\n"

        self.log_to_message_window(log_entry, tag)

    def log_to_message_window(self, message, tag):
        """A thread-safe method to append text to the message window."""
        self.message_text.config(state='normal')
        self.message_text.insert(tk.END, message + "\n", (tag,))
        self.message_text.config(state='disabled')
        self.message_text.see(tk.END)

    def send_message(self):
        """Sends a broadcast or direct message based on node selection."""
        if not self.is_connected:
            messagebox.showerror("Error", "Not connected to a device.")
            return
        
        message = self.message_entry.get()
        if not message:
            return

        destination_id = None
        selected_items = self.node_tree.selection()
        if selected_items:
            selected_node = self.node_tree.item(selected_items[0])
            destination_id = selected_node['values'][1]
        
        self.message_entry.delete(0, tk.END)

        if destination_id:
            threading.Thread(
                target=self.send_direct_message_thread,
                args=(destination_id, message),
                daemon=True
            ).start()
        else:
            channel_name = self.channel_combobox.get()
            channel_index = self.channel_map.get(channel_name, 0)
            self.log_to_message_window(f"Sending broadcast to '{channel_name}': '{message}'", "info")
            self.interface.sendText(message, channelIndex=channel_index)

    def send_direct_message_thread(self, destination_id, message):
        """Thread worker for sending a DM and waiting for an ACK."""
        try:
            with self.acks_lock:
                self.ack_received_event.clear()
                self.ack_response_status = "UNKNOWN"
                self.waiting_for_ack_from = destination_id
            
            self.after(0, self.log_to_message_window, f"Sending DM to {destination_id} and waiting for ACK...", "info")
            
            self.interface.sendText(
                message,
                destinationId=destination_id,
                wantAck=True
            )

            self.ack_received_event.wait(timeout=15.0)
            
            with self.acks_lock:
                status = self.ack_response_status
                self.waiting_for_ack_from = None

            if status == 'NONE':
                self.after(0, self.log_to_message_window, f"Message delivered successfully to {destination_id}!", "success")
            elif status == 'UNKNOWN':
                self.after(0, self.log_to_message_window, f"Message to {destination_id} timed out.", "warning")
            else:
                self.after(0, self.log_to_message_window, f"Message to {destination_id} failed: {status}", "error")

        except Exception as e:
            self.after(0, self.log_to_message_window, f"Failed to send DM: {e}", "error")


    def on_node_double_click(self, event):
        """Handles the double-click event on the node list."""
        selected_item = self.node_tree.selection()
        if not selected_item:
            return
            
        item = self.node_tree.item(selected_item[0])
        node_id = item['values'][1]

        if self.interface and node_id in self.interface.nodes:
            self.show_node_info_window(self.interface.nodes[node_id])

    def show_node_info_window(self, node_info):
        """Displays a new window with detailed information about a node."""
        win = tk.Toplevel(self)
        win.title("Node Information")

        user = node_info.get('user', {})
        pos = node_info.get('position', {})
        metrics = node_info.get('deviceMetrics', {})

        long_name = user.get('longName', 'N/A')
        short_name = user.get('shortName', 'N/A')
        
        win.geometry("350x300")
        win.transient(self) # Keep window on top
        
        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Long Name:").grid(row=0, column=0, sticky='w')
        ttk.Label(frame, text=long_name, font='-weight bold').grid(row=0, column=1, sticky='w')

        ttk.Label(frame, text="Short Name:").grid(row=1, column=0, sticky='w')
        ttk.Label(frame, text=short_name).grid(row=1, column=1, sticky='w')

        ttk.Label(frame, text="Node ID:").grid(row=2, column=0, sticky='w')
        ttk.Label(frame, text=user.get('id', 'N/A')).grid(row=2, column=1, sticky='w')
        
        ttk.Label(frame, text="Hardware:").grid(row=3, column=0, sticky='w')
        ttk.Label(frame, text=user.get('hwModel', 'N/A')).grid(row=3, column=1, sticky='w')

        ttk.Separator(frame, orient='horizontal').grid(row=4, columnspan=2, sticky='ew', pady=10)

        lat = pos.get('latitude', 'N/A')
        lon = pos.get('longitude', 'N/A')
        ttk.Label(frame, text="Latitude:").grid(row=5, column=0, sticky='w')
        ttk.Label(frame, text=f"{lat:.5f}" if isinstance(lat, float) else lat).grid(row=5, column=1, sticky='w')
        
        ttk.Label(frame, text="Longitude:").grid(row=6, column=0, sticky='w')
        ttk.Label(frame, text=f"{lon:.5f}" if isinstance(lon, float) else lon).grid(row=6, column=1, sticky='w')

        ttk.Separator(frame, orient='horizontal').grid(row=7, columnspan=2, sticky='ew', pady=10)

        bat = metrics.get('batteryLevel', 101)
        battery_str = "Unknown"
        if bat <= 100:
            battery_str = f"{bat}%"
        ttk.Label(frame, text="Battery:").grid(row=8, column=0, sticky='w')
        ttk.Label(frame, text=battery_str).grid(row=8, column=1, sticky='w')

        snr = node_info.get('snr', 'N/A')
        ttk.Label(frame, text="Last SNR:").grid(row=9, column=0, sticky='w')
        ttk.Label(frame, text=f"{snr:.2f} dB" if isinstance(snr, float) else snr).grid(row=9, column=1, sticky='w')

    def on_closing(self):
        """Handles the window close event to ensure a clean shutdown."""
        if self.is_connected:
            threading.Thread(target=self.disconnect_from_device, daemon=True).start()
        self.destroy()

if __name__ == "__main__":
    # You may need to install pyserial, meshtastic, and pypubsub:
    # pip install pyserial meshtastic pypubsub
    app = MeshtasticGUI()
    app.mainloop()

