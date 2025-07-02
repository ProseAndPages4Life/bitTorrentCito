import socket

def register_with_tracker(tracker_ip, tracker_port, node_id, files):
    tracker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tracker.connect((tracker_ip, tracker_port))
    tracker.send(f"REGISTER:{node_id}:{':'.join(files)}".encode())
    response = tracker.recv(1024).decode()
    print(f"Tracker Response: {response}")
    tracker.close()

tracker_ip = "127.0.0.1"
tracker_port = 8000
node_id = "NodeA"
files = ["file1.txt", "file2.mp4"]

register_with_tracker(tracker_ip, tracker_port, node_id, files)
def request_file(tracker_ip, tracker_port, file_name):
    tracker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tracker.connect((tracker_ip, tracker_port))
    tracker.send(f"REQUEST:{file_name}".encode())
    response = tracker.recv(1024).decode()
    print(f"Peers with file {file_name}: {response}")
    tracker.close()

# Solicitar un archivo
request_file(tracker_ip, tracker_port, "file1.txt")
