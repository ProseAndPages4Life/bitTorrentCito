import socket
import threading

nodes = {}  # Diccionario para almacenar información de los nodos

def handle_client(client_socket, addr):
    """
    Función para manejar cada cliente (nodo) que se conecta al tracker.
    """
    print(f"[CONEXIÓN] Nodo conectado desde {addr}")
    while True:
        try:
            data = client_socket.recv(1024).decode()
            if not data:
                break

            command = data.split(":")
            if command[0] == "REGISTER":
                # Registrar nodo y archivos
                node_id = command[1]
                node_port = command[2]
                files = command[3:]
                nodes[node_id] = {"ip": addr[0], "port": node_port, "files": files}
                client_socket.send(f"REGISTERED:{node_id}".encode())
                print(f"[REGISTRO] Nodo {node_id} registrado con archivos: {files}")
            elif command[0] == "REQUEST":
                # Solicitar información sobre nodos con un archivo
                file_requested = command[1]
                peers = [
                    f"{node_id}:{info['ip']}:{info['port']}"
                    for node_id, info in nodes.items()
                    if file_requested in info["files"]
                ]
                client_socket.send(",".join(peers).encode())
                print(f"[SOLICITUD] Nodo solicitó {file_requested}, encontrado en: {peers}")
        except Exception as e:
            print(f"[ERROR] {e}")
            break

    client_socket.close()
    print(f"[DESCONECTADO] Nodo {addr} desconectado.")

def start_tracker(host="0.0.0.0", port=8000):
    """
    Inicia el servidor tracker.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((host, port))
    server.listen(5)
    print(f"[TRACKER] Servidor ejecutándose en {host}:{port}")

    while True:
        client_socket, addr = server.accept()
        threading.Thread(target=handle_client, args=(client_socket, addr)).start()

if __name__ == "__main__":
    start_tracker()
