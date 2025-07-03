import socket
import threading
import os
import json

CHUNK_SIZE = 1024 * 1024  # Tamaño de los fragmentos (1 MB)
tracker_ip = "127.0.0.1"
tracker_port = 8000
progress_file = "progress.json"  # Archivo para guardar el estado de descargas

def register_with_tracker(node_id, node_port, files):
    """
    Registra el nodo con el Tracker, incluyendo el puerto del nodo.
    """
    tracker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tracker.connect((tracker_ip, tracker_port))
    tracker.send(f"REGISTER:{node_id}:{node_port}:{':'.join(files)}".encode())
    response = tracker.recv(1024).decode()
    print(f"Tracker Response: {response}")
    tracker.close()

def request_file(file_name):
    """
    Solicita al Tracker información sobre nodos que tienen el archivo.
    """
    tracker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tracker.connect((tracker_ip, tracker_port))
    tracker.send(f"REQUEST:{file_name}".encode())
    response = tracker.recv(4096).decode()  # Aumentar el buffer si hay muchos peers
    tracker.close()
    return response.split(",")  # Retorna una lista de nodos en formato 'node_id:ip:port'

def handle_peer_connection(peer_socket):
    """
    Maneja conexiones entrantes desde otros nodos.
    """
    try:
        data = peer_socket.recv(1024).decode()
        if data.startswith("GET_SIZE"):
            _, file_name = data.split(":")
            send_file_size(peer_socket, file_name)
        elif data.startswith("DOWNLOAD"):
            _, file_name, start, end = data.split(":")
            send_file_fragment(peer_socket, file_name, int(start), int(end))
        else:
            print(f"[ERROR] Comando no reconocido: {data}")
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        peer_socket.close()

def send_file_size(peer_socket, file_name):
    """
    Envía el tamaño del archivo solicitado.
    """
    try:
        current_dir = os.getcwd()
        file_path = os.path.join(current_dir, "peers", file_name)
        if not os.path.exists(file_path):
            print(f"[ERROR] El archivo {file_path} no existe.")
            peer_socket.send(b"ERROR: Archivo no encontrado.")
            return
        file_size = os.path.getsize(file_path)
        peer_socket.send(f"SIZE:{file_size}".encode())
        print(f"[DEBUG] Tamaño de {file_name} enviado: {file_size} bytes.")
    except Exception as e:
        print(f"[ERROR] Error al enviar tamaño de archivo: {e}")
        peer_socket.send(b"ERROR: Error inesperado.")

def send_file_fragment(peer_socket, file_name, start, end):
    """
    Envía un fragmento específico del archivo solicitado.
    """
    try:
        current_dir = os.getcwd()
        file_path = os.path.join(current_dir, "peers", file_name)
        if not os.path.exists(file_path):
            print(f"[ERROR] El archivo {file_path} no existe.")
            peer_socket.send(b"ERROR: Archivo no encontrado.")
            return
        with open(file_path, "rb") as f:
            f.seek(start)
            bytes_to_read = end - start + 1
            while bytes_to_read > 0:
                chunk = f.read(min(CHUNK_SIZE, bytes_to_read))
                if not chunk:
                    break
                peer_socket.send(chunk)
                bytes_to_read -= len(chunk)
            peer_socket.send(b"DONE")
            print(f"[DEBUG] Enviado fragmento {start}-{end} de {file_name}.")
    except Exception as e:
        print(f"[ERROR] Error al enviar fragmento: {e}")
        peer_socket.send(b"ERROR: Error inesperado.")

def start_node_server(node_port):
    """
    Inicia un servidor para escuchar solicitudes entrantes desde otros nodos.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("0.0.0.0", node_port))
    server.listen(5)
    print(f"Servidor del nodo ejecutándose en el puerto {node_port}")

    while True:
        peer_socket, addr = server.accept()
        threading.Thread(target=handle_peer_connection, args=(peer_socket,)).start()

if __name__ == "__main__":
    # Configuración inicial del nodo
    node_id = "NodeC"   # Identificador único para este nodo
    node_port = 8003    # Puerto único para este nodo
    shared_files = ["file5.mp4", "file6.txt", "file_large.mp4"]  # Archivos compartidos por este nodo

    # Inicia el servidor del nodo en un hilo separado
    threading.Thread(target=start_node_server, args=(node_port,), daemon=True).start()

    # Registra el nodo con el Tracker
    register_with_tracker(node_id, node_port, shared_files)
