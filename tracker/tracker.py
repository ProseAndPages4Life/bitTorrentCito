import socket
import threading
import sys # Importar sys para sys.exit

nodes = {}  # Diccionario para almacenar información de los nodos: {node_id: {"ip": str, "port": str, "files": list}}

def handle_client(client_socket, addr):
    """
    Función para manejar cada cliente (nodo) que se conecta al tracker.
    """
    print(f"[CONEXIÓN] Nodo conectado desde {addr}")
    try:
        while True:
            # Usar 'utf-8' para decodificar
            data = client_socket.recv(1024).decode('utf-8')
            if not data:
                break # Cliente desconectado

            command_parts = data.split(":")
            command = command_parts[0]

            if command == "REGISTER":
                # REGISTER:node_id:node_port:file1:file2:...
                node_id = command_parts[1]
                node_port = command_parts[2]
                files = command_parts[3:] if len(command_parts) > 3 else []
                # Utilizar addr[0] como la IP registrada (IP pública del router si hay NAT)
                nodes[node_id] = {"ip": addr[0], "port": node_port, "files": files}
                client_socket.send(f"REGISTERED:{node_id}".encode('utf-8')) # Codificar la respuesta
                print(f"[REGISTRO] Nodo {node_id} registrado con IP: {addr[0]}, Puerto: {node_port}, Archivos: {files}")
            elif command == "REQUEST":
                # REQUEST:file_name
                file_requested = command_parts[1]
                peers = [
                    f"{node_id}:{info['ip']}:{info['port']}"
                    for node_id, info in nodes.items()
                    if file_requested in info["files"]
                ]
                client_socket.send(",".join(peers).encode('utf-8')) # Codificar la respuesta
                print(f"[SOLICITUD] Nodo {addr} solicitó '{file_requested}', encontrado en: {peers if peers else 'ninguno'}")
            elif command == "LIST_ALL_FILES":
                # LIST_ALL_FILES
                all_available_files = {}
                for node_id, info in nodes.items():
                    for file_name in info["files"]:
                        if file_name not in all_available_files:
                            all_available_files[file_name] = []
                        if node_id not in all_available_files[file_name]: # Evitar duplicados
                            all_available_files[file_name].append(node_id)
                
                # Formato de respuesta: file1:nodeA,nodeB;file2:nodeC
                response_parts = []
                for file_name, node_ids in all_available_files.items():
                    response_parts.append(f"{file_name}:{','.join(sorted(node_ids))}") # Ordenar nodes_id para consistencia
                
                client_socket.send(";".join(response_parts).encode('utf-8')) # Codificar la respuesta
                print(f"[LISTADO] Nodo {addr} solicitó lista de archivos. Enviado: {all_available_files}")
            else:
                print(f"[ERROR] Comando no reconocido del nodo {addr}: {data}")
                client_socket.send("ERROR: Comando no reconocido.".encode('utf-8')) # Codificar la respuesta
    except Exception as e:
        print(f"[ERROR] Error manejando cliente {addr}: {e}")
    finally:
        client_socket.close()
        print(f"[DESCONECTADO] Nodo {addr} desconectado.")

def start_tracker(host="0.0.0.0", port=8000):
    """
    Inicia el servidor tracker.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((host, port))
        server.listen(5)
        print(f"[TRACKER] Servidor ejecutándose en {host}:{port}")

        while True:
            client_socket, addr = server.accept()
            threading.Thread(target=handle_client, args=(client_socket, addr)).start()
    except Exception as e:
        print(f"[CRITICAL ERROR] Error al iniciar el Tracker: {e}")
        sys.exit(1)

if __name__ == "__main__":
    start_tracker()