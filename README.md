Meshtastic Python CLI Tool
This is a powerful, internet-independent command-line tool to interact with your Meshtastic devices directly from your computer via USB or Bluetooth.

1. Prerequisites: Python
This tool requires Python 3. To check if you have it, open a terminal or command prompt and run:

python3 --version

If you see a version number (e.g., Python 3.9.6), you're all set.

If not, you'll need to install it. The official and easiest way is to download it from the Python website:

Download Python for Windows, macOS, or Linux

During installation, make sure to check the box that says "Add Python to PATH".

2. Install the Meshtastic Library
Once Python is installed, you can install the official Meshtastic Python library using pip, Python's package manager.

Open your terminal or command prompt and run:

pip install meshtastic

This will download and install the necessary library to communicate with your device. This step requires internet, but once it's done, the tool itself will work completely offline.

(Windows Only) USB Drivers:
If you are on Windows, you may need to install the CP210x USB drivers for your computer to recognize the device. You can download them here: Silicon Labs CP210x Drivers

3. Running the Tool
Connect Your Device: Plug your Meshtastic device into your computer using a USB cable. Make sure it's a data cable, not just a charging cable.

Save the Script: Save the meshtastic_tool.py file to a known location on your computer (e.g., your Desktop).

Run from Terminal:

Open a terminal or command prompt.

Navigate to the directory where you saved the file. For example: cd Desktop

Run the script with the following command:

python meshtastic_tool.py

What to Expect
The tool will start, connect to your device, and you will see:

Information about your node.

A list of all other nodes in the mesh that your node knows about.

A message saying "Waiting for messages...".

As new packets are received, they will be printed to the console in real-time.

To stop the tool, press Ctrl+C in the terminal.