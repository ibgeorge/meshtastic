import time
from pubsub import pub
import sys
import os
import threading

# You may need to install the colorama library: pip install colorama
import colorama
from colorama import Fore, Style

# Import the Meshtastic library
import meshtastic
import meshtastic.serial_interface

# --- Configuration ---
# A node is considered "online" if it has been heard from in the last 30 minutes.
ONLINE_THRESHOLD_SECONDS = 30 * 60
# The online node list will be automatically printed every 15 minutes.
PERIODIC_UPDATE_INTERVAL_SECONDS = 15 * 60

# --- Globals for ACK handling ---
ack_received_event = threading.Event()
ack_response_status = "UNKNOWN"
acks_lock = threading.Lock()
waiting_for_ack_from = None


def on_receive(packet, interface):
    """Callback function that is called when a new packet is received."""
    global ack_response_status, waiting_for_ack_from
    try:
        decoded = packet.get('decoded')
        if not decoded:
            return

        message_type = decoded.get('portnum', 'N_A')
        from_node_id = packet.get('fromId', 'N/A')

        # --- New ACK Handling Logic ---
        with acks_lock:
            if waiting_for_ack_from and from_node_id == waiting_for_ack_from and message_type == 'ROUTING_APP':
                routing = decoded.get('routing', {})
                error = routing.get('errorReason', 'UNKNOWN_RESPONSE')
                ack_response_status = error
                ack_received_event.set()
                # We have handled this packet as an ACK, so we can return early
                return
        # --- End of New ACK Logic ---
        
        is_direct = packet.get('toId') == interface.myInfo.my_node_num if interface.myInfo else False
        direct_str = "[DIRECT] " if is_direct else ""

        title_text = f"    {direct_str}New Packet Received    "
        width = len(title_text)
        print(f"\n{Style.BRIGHT}{Fore.BLUE}╔{'═' * width}╗{Style.RESET_ALL}")
        print(f"{Style.BRIGHT}{Fore.BLUE}║{title_text}║{Style.RESET_ALL}")
        print(f"{Style.BRIGHT}{Fore.BLUE}╚{'═' * width}╝{Style.RESET_ALL}")
        
        from_str = from_node_id
        if from_node_id in interface.nodes:
            node_info = interface.nodes[from_node_id]
            user = node_info.get('user')
            if user:
                long_name = user.get('longName')
                short_name = user.get('shortName')
                safe_long = long_name.encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding) if long_name else None
                safe_short = short_name.encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding) if short_name else None
                
                display_name = ""
                if safe_long:
                    display_name = f"{Fore.MAGENTA}{safe_long}{Style.RESET_ALL}"
                    if safe_short:
                        display_name += f" [{Fore.YELLOW}{safe_short}{Style.RESET_ALL}]"
                elif safe_short:
                    display_name = f"{Fore.YELLOW}{safe_short}{Style.RESET_ALL}"
                
                if display_name:
                    from_str = f"{display_name} ({from_node_id})"
        
        print(f"  {Fore.CYAN}{'From:':<12}{Style.RESET_ALL}{from_str}")
        print(f"  {Fore.CYAN}{'Type:':<12}{Style.RESET_ALL}{message_type}")

        if message_type == 'TEXT_MESSAGE_APP' and 'text' in decoded:
            message_text = decoded['text']
            safe_message = message_text.encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding)
            print(f"  {Fore.CYAN}{'Message:':<12}{Fore.GREEN}\"{safe_message}\"{Style.RESET_ALL}")
        elif message_type == 'POSITION_APP' and 'position' in decoded:
            pos = decoded['position']
            lat = pos.get('latitude', 'N/A')
            lon = pos.get('longitude', 'N/A')
            print(f"  {Fore.CYAN}{'Position:':<12}{Style.RESET_ALL}Lat={lat}, Lon={lon}")
        else:
            print(f"  {Fore.CYAN}{'Data:':<12}{Style.RESET_ALL}{decoded}")

        snr = packet.get('rxSnr', 'N/A')
        print(f"  {Fore.CYAN}{'SNR:':<12}{Style.RESET_ALL}{snr} dB")
        print(f"{Style.DIM}-----------------------------------{Style.RESET_ALL}")


    except Exception as e:
        print(f"Error processing packet: {e}")


def on_nodes_updated(interface, nodes):
    """Callback function that prints all known nodes, sorted by last heard."""
    print(f"\n{Style.BRIGHT}{Fore.BLUE}╔═════════════════════════╗{Style.RESET_ALL}")
    print(f"{Style.BRIGHT}{Fore.BLUE}║     All Known Nodes     ║{Style.RESET_ALL}")
    print(f"{Style.BRIGHT}{Fore.BLUE}╚═════════════════════════╝{Style.RESET_ALL}")
    if not nodes:
        print("No nodes found in the database yet.")
        return
        
    my_node_id_str = f"!{interface.myInfo.my_node_num:08x}" if interface.myInfo else None
    sorted_nodes = sorted(nodes.items(), key=lambda item: item[1].get('lastHeard', 0), reverse=True)

    for node_id, node_info in sorted_nodes:
        print_single_node(node_id, node_info, my_node_id_str)
            
    print(f"{Style.DIM}--------------------------------------------------{Style.RESET_ALL}\n")


def print_online_nodes(interface):
    """Filters and prints only the nodes considered 'online'."""
    mins = int(ONLINE_THRESHOLD_SECONDS / 60)
    header_text = f" Online Nodes (Last {mins} mins) "
    print(f"\n{Style.BRIGHT}{Fore.BLUE}╔{'═' * (len(header_text))}╗{Style.RESET_ALL}")
    print(f"{Style.BRIGHT}{Fore.BLUE}║{header_text}║{Style.RESET_ALL}")
    print(f"{Style.BRIGHT}{Fore.BLUE}╚{'═' * (len(header_text))}╝{Style.RESET_ALL}")

    if not interface.nodes:
        print("No nodes found in the database yet.")
        return

    my_node_id_str = f"!{interface.myInfo.my_node_num:08x}" if interface.myInfo else None
    online_cutoff = time.time() - ONLINE_THRESHOLD_SECONDS
    
    online_nodes = {
        node_id: node_info for node_id, node_info in interface.nodes.items()
        if node_info.get('lastHeard', 0) > online_cutoff
    }
    
    if not online_nodes:
        print("No nodes appear to be online.")
        print(f"{Style.DIM}--------------------------------------------------{Style.RESET_ALL}\n")
        return

    sorted_nodes = sorted(online_nodes.items(), key=lambda item: item[1].get('lastHeard', 0), reverse=True)

    for node_id, node_info in sorted_nodes:
        print_single_node(node_id, node_info, my_node_id_str)

    print(f"{Style.DIM}--------------------------------------------------{Style.RESET_ALL}\n")


def print_single_node(node_id, node_info, my_node_id_str):
    """Prints a formatted line for a single node."""
    user = node_info.get('user')
    if not user:
        return

    is_me = f"{Fore.CYAN}(Me){Style.RESET_ALL}" if node_id == my_node_id_str else ""
    
    long_name = user.get('longName')
    short_name = user.get('shortName')
    
    safe_long = long_name.encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding) if long_name else None
    safe_short = short_name.encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding) if short_name else None

    display_name = ""
    if safe_long:
        display_name = f"{Fore.MAGENTA}{safe_long}{Style.RESET_ALL}"
        if safe_short:
            display_name += f" [{Fore.YELLOW}{safe_short}{Style.RESET_ALL}]"
    elif safe_short:
        display_name = f"{Fore.YELLOW}{safe_short}{Style.RESET_ALL}"
    else:
        display_name = f"{Style.DIM}N/A{Style.RESET_ALL}"
    
    print(f"\n{Style.BRIGHT}» {display_name} {is_me}{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}{'ID:':<12}{Style.RESET_ALL}{node_id}")
    
    last_heard_ts = node_info.get('lastHeard')
    if last_heard_ts:
        last_heard_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_heard_ts))
        print(f"  {Fore.CYAN}{'Last Heard:':<12}{Style.RESET_ALL}{last_heard_str}")
        
    snr = node_info.get('snr')
    if snr:
        print(f"  {Fore.CYAN}{'SNR:':<12}{Style.RESET_ALL}{snr:.2f} dB")


def periodic_update_thread(interface, exit_event):
    """A thread that periodically prints the online node list."""
    while not exit_event.is_set():
        if not exit_event.wait(timeout=PERIODIC_UPDATE_INTERVAL_SECONDS):
            print_online_nodes(interface)


def handle_config_command(interface, parts):
    """Handles all 'config' subcommands."""
    if len(parts) < 2:
        print(f"{Fore.RED}Invalid config command. Try 'config set' or 'config reboot'.{Style.RESET_ALL}")
        return

    sub_command = parts[1]
    if sub_command == "reboot":
        print("Rebooting device...")
        interface.reboot()
        print("Device is rebooting. The script may need to be restarted.")
    elif sub_command == "set":
        if len(parts) < 4:
            print(f"{Fore.RED}Invalid 'config set' command. Try 'config set owner <long> [short]' or 'config set pos <lat> <lon>'.{Style.RESET_ALL}")
            return
        
        setting = parts[2]
        if setting == "owner":
            long_name = parts[3]
            short_name = parts[4] if len(parts) > 4 else long_name[:4]
            print(f"Setting owner to Long='{long_name}', Short='{short_name}'...")
            interface.localNode.setOwner(long_name=long_name, short_name=short_name)
            print("Owner set. You may need to reboot the device for changes to be visible everywhere.")
        elif setting == "pos":
            if len(parts) < 5:
                print(f"{Fore.RED}Invalid 'config set pos' command. Provide latitude and longitude.{Style.RESET_ALL}")
                return
            try:
                lat = float(parts[3])
                lon = float(parts[4])
                print(f"Setting fixed position to Lat={lat}, Lon={lon}...")
                interface.localNode.setFixedPosition(lat, lon)
                print("Position set. You may need to reboot the device.")
            except ValueError:
                print(f"{Fore.RED}Invalid latitude/longitude. Please provide numbers.{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}Unknown setting '{setting}'. Try 'owner' or 'pos'.{Style.RESET_ALL}")


def send_direct_message_and_wait(interface, target_identifier, destination_node_id, message):
    """Sends a DM in a background thread and waits for an ACK."""
    global ack_response_status, waiting_for_ack_from
    try:
        with acks_lock:
            ack_received_event.clear()
            ack_response_status = "UNKNOWN"
            waiting_for_ack_from = destination_node_id
        
        print(f"\nSending direct message to {target_identifier} and waiting for acknowledgment...")
        
        interface.sendText(message, 
                           destinationId=destination_node_id, 
                           wantAck=True)
        
        # Wait for the on_receive callback to fire our event
        ack_received_event.wait(timeout=15.0) 
        
        with acks_lock:
            status = ack_response_status
            waiting_for_ack_from = None
        
        # Print the final status message
        if status == 'NONE':
            print(f"\n{Fore.GREEN}Message delivered successfully to {target_identifier}!{Style.RESET_ALL}")
        elif status == 'UNKNOWN': # This means the event timed out
            print(f"\n{Fore.YELLOW}Message sent, but no acknowledgment was received (timeout).{Style.RESET_ALL}")
        else:
            print(f"\n{Fore.RED}Message failed to deliver to {target_identifier}. Reason: {status}{Style.RESET_ALL}")

    except Exception as e:
        print(f"\n{Fore.RED}Failed to send message: {e}{Style.RESET_ALL}")


def main():
    """Main function to connect to the device and listen for events."""
    colorama.init()
    interface = None
    exit_event = threading.Event()
    
    print(f"{Style.BRIGHT}{Fore.CYAN}--- Meshtastic Python Tool ---{Style.RESET_ALL}")
    print("Attempting to connect to a Meshtastic device via USB/Serial...")

    try:
        interface = meshtastic.serial_interface.SerialInterface()
        print(f"{Fore.GREEN}Connection established successfully!{Style.RESET_ALL}")
        
        update_thread = threading.Thread(target=periodic_update_thread, args=(interface, exit_event), daemon=True)
        update_thread.start()

        pub.subscribe(on_receive, "meshtastic.receive", interface=interface)

        print("\nWaiting 2 seconds for initial data sync...")
        time.sleep(2)

        print_online_nodes(interface=interface)
        
        print(f"{Style.BRIGHT}{Fore.BLUE}╔{'═' * 70}╗{Style.RESET_ALL}")
        print(f"{Style.BRIGHT}{Fore.BLUE}║ {'Commands':^68} ║{Style.RESET_ALL}")
        print(f"{Style.BRIGHT}{Fore.BLUE}╠{'═' * 70}╣{Style.RESET_ALL}")
        
        broadcast_cmd = '<message> (no ack)'
        dm_cmd = 'dm <name> <msg> (waits for ack)'
        nodes_cmd = "'nodes all' or 'nodes online'"
        owner_cmd = 'config set owner <long> [short]'
        pos_cmd = 'config set pos <lat> <lon>'
        reboot_cmd = 'config reboot'
        exit_cmd = "'exit' or Ctrl+C"

        print(f"{Style.BRIGHT}{Fore.BLUE}║ {Fore.CYAN}{'Broadcast:':<15}{Style.RESET_ALL} {Fore.WHITE}{broadcast_cmd:<52}{Style.BRIGHT}{Fore.BLUE} ║{Style.RESET_ALL}")
        print(f"{Style.BRIGHT}{Fore.BLUE}║ {Fore.CYAN}{'Direct Message:':<15}{Style.RESET_ALL} {Fore.WHITE}{dm_cmd:<52}{Style.BRIGHT}{Fore.BLUE} ║{Style.RESET_ALL}")
        print(f"{Style.BRIGHT}{Fore.BLUE}║ {Fore.CYAN}{'Node Lists:':<15}{Style.RESET_ALL} {Fore.WHITE}{nodes_cmd:<52}{Style.BRIGHT}{Fore.BLUE} ║{Style.RESET_ALL}")
        print(f"{Style.BRIGHT}{Fore.BLUE}║ {Fore.CYAN}{'Set Owner:':<15}{Style.RESET_ALL} {Fore.WHITE}{owner_cmd:<52}{Style.BRIGHT}{Fore.BLUE} ║{Style.RESET_ALL}")
        print(f"{Style.BRIGHT}{Fore.BLUE}║ {Fore.CYAN}{'Set Position:':<15}{Style.RESET_ALL} {Fore.WHITE}{pos_cmd:<52}{Style.BRIGHT}{Fore.BLUE} ║{Style.RESET_ALL}")
        print(f"{Style.BRIGHT}{Fore.BLUE}║ {Fore.CYAN}{'Reboot Device:':<15}{Style.RESET_ALL} {Fore.WHITE}{reboot_cmd:<52}{Style.BRIGHT}{Fore.BLUE} ║{Style.RESET_ALL}")
        print(f"{Style.BRIGHT}{Fore.BLUE}║ {Fore.CYAN}{'Exit:':<15}{Style.RESET_ALL} {Fore.WHITE}{exit_cmd:<52}{Style.BRIGHT}{Fore.BLUE} ║{Style.RESET_ALL}")
        
        print(f"{Style.BRIGHT}{Fore.BLUE}╚{'═' * 70}╝{Style.RESET_ALL}\n")

        while True:
            try:
                raw_input_str = input(f"{Style.BRIGHT}> {Style.RESET_ALL}")
                if not raw_input_str:
                    continue
                
                cmd = raw_input_str.lower()
                parts = raw_input_str.split(' ')

                if cmd == 'exit':
                    break
                elif cmd == 'nodes all':
                    on_nodes_updated(interface, interface.nodes)
                elif cmd == 'nodes online':
                    print_online_nodes(interface)
                elif cmd.startswith('dm '):
                    if len(parts) >= 3:
                        target_identifier = parts[1]
                        message = " ".join(parts[2:])
                        destination_node_id = None
                        
                        if target_identifier.startswith('!'):
                            destination_node_id = target_identifier
                        else:
                            found_nodes = []
                            for node_id_key, node_info in interface.nodes.items():
                                user = node_info.get('user', {})
                                if target_identifier.lower() in [user.get('longName', '').lower(), user.get('shortName', '').lower()]:
                                    found_nodes.append(node_id_key)
                            
                            if len(found_nodes) == 1:
                                destination_node_id = found_nodes[0]
                            elif len(found_nodes) > 1:
                                print(f"{Fore.RED}Multiple nodes found. Please use the full node ID.{Style.RESET_ALL}")
                            else:
                                print(f"{Fore.RED}Node '{target_identifier}' not found.{Style.RESET_ALL}")

                        if destination_node_id:
                            # Create and start a thread to handle sending and waiting
                            sender_thread = threading.Thread(
                                target=send_direct_message_and_wait,
                                args=(interface, target_identifier, destination_node_id, message),
                                daemon=True
                            )
                            sender_thread.start()
                    else:
                        print("Invalid format. Use: dm <node_id_or_name> <message>")
                elif cmd.startswith('config '):
                    handle_config_command(interface, parts)
                else:
                    print("Sending broadcast message (no delivery confirmation)...")
                    interface.sendText(raw_input_str)

            except EOFError:
                break

    except KeyboardInterrupt:
        print("\nCTRL+C detected. Shutting down gracefully...")
    except Exception as e:
        print(f"\n[ERROR] An error occurred: {e}")
    finally:
        print("\nClosing interface...")
        exit_event.set()
        if interface:
            interface.close()
        print("Goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()

