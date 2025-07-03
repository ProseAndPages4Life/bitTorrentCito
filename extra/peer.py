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

def save_progress(file_name, fragments):
    """
    Guarda el progreso de descargas en un archivo JSON.
    """
    try:
        if os.path.exists(progress_file):
            with open(progress_file, "r") as f:
                progress_data = json.load(f)
        else:
            progress_data = {}

        progress_data[file_name] = fragments
        with open(progress_file, "w") as f:
            json.dump(progress_data, f, indent=4)

        print(f"[INFO] Progreso guardado en {progress_file}.")
    except Exception as e:
        print(f"[ERROR] No se pudo guardar el progreso: {e}")

def load_progress():
    """
    Carga el progreso de descargas desde un archivo JSON.
    """
    try:
        if os.path.exists(progress_file):
            with open(progress_file, "r") as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"[ERROR] No se pudo cargar el progreso: {e}")
        return {}

def get_file_size(peer_ip, peer_port, file_name):
    """
    Solicita el tamaño del archivo a un peer.
    """
    try:
        peer = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        peer.connect((peer_ip, peer_port))
        peer.send(f"GET_SIZE:{file_name}".encode())
        response = peer.recv(1024).decode()
        peer.close()
        if response.startswith("SIZE:"):
            return int(response.split(":")[1])
        else:
            print(f"[ERROR] Respuesta inesperada al solicitar tamaño: {response}")
            return None
    except ConnectionRefusedError:
        print(f"[ERROR] No se pudo conectar al peer {peer_ip}:{peer_port}.")
        return None
    except Exception as e:
        print(f"[ERROR] Error al obtener tamaño del archivo: {e}")
        return None

def download_file_simultaneously(file_name):
    """
    Descarga un archivo completo desde múltiples nodos simultáneamente.
    """
    # Cargar el progreso guardado
    progress = load_progress()
    fragments = progress.get(file_name, {})

    # Obtener la lista de peers que tienen el archivo
    peers = request_file(file_name)
    peers = [peer for peer in peers if peer]  # Eliminar entradas vacías
    if not peers:
        print(f"[INFO] No hay peers disponibles con el archivo {file_name}.")
        return

    # Intentar obtener el tamaño del archivo desde cualquier peer disponible
    file_size = None
    for peer_info in peers:
        peer_ip, peer_port = peer_info.split(":")[1], int(peer_info.split(":")[2])
        file_size = get_file_size(peer_ip, peer_port, file_name)
        if file_size is not None:
            break

    if file_size is None:
        print(f"[ERROR] No se pudo obtener el tamaño del archivo {file_name}.")
        return

    # Dividir el archivo en fragmentos
    fragment_size = file_size // len(peers)
    threads = []
    fragment_paths = []

    for i, peer in enumerate(peers):
        peer_info = peer.split(":")
        if len(peer_info) != 3:
            print(f"[ERROR] Formato incorrecto en la información del peer: {peer}")
            continue
        peer_ip, peer_port = peer_info[1], int(peer_info[2])

        start = i * fragment_size
        end = (start + fragment_size - 1) if i < len(peers) - 1 else file_size - 1

        # Verificar si el fragmento ya fue descargado
        fragment_id = f"{start}-{end}"
        if fragments.get(fragment_id) == "complete":
            print(f"[INFO] Fragmento {fragment_id} ya descargado.")
            continue

        fragment_path = os.path.join(os.getcwd(), "peers", f"{file_name}.part{i}")
        fragment_paths.append((fragment_path, fragment_id, start, end, peer_ip, peer_port))

    # Descargar fragmentos pendientes
    for fragment_path, fragment_id, start, end, peer_ip, peer_port in fragment_paths:
        thread = threading.Thread(
            target=download_fragment,
            args=(peer_ip, peer_port, file_name, start, end, fragment_path, fragment_id, fragments)
        )
        threads.append(thread)
        thread.start()

    # Esperar a que todos los hilos terminen
    for thread in threads:
        thread.join()

    # Combinar fragmentos en un archivo completo
    combined_path = os.path.join(os.getcwd(), "peers", f"downloaded_{file_name}")
    with open(combined_path, "wb") as outfile:
        for fragment_path, _, _, _, _, _ in fragment_paths:
            with open(fragment_path, "rb") as infile:
                outfile.write(infile.read())
            os.remove(fragment_path)

    print(f"[INFO] Archivo {file_name} descargado y combinado correctamente en {combined_path}.")

    # Guardar el progreso final
    for _, fragment_id, _, _, _, _ in fragment_paths:
        fragments[fragment_id] = "complete"
    save_progress(file_name, fragments)

def download_fragment(peer_ip, peer_port, file_name, start, end, fragment_path, fragment_id, fragments):
    """
    Descarga un fragmento específico de un archivo desde un peer.
    """
    try:
        peer = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        peer.connect((peer_ip, peer_port))
        peer.send(f"DOWNLOAD:{file_name}:{start}:{end}".encode())
        with open(fragment_path, "wb") as f:
            while True:
                data = peer.recv(CHUNK_SIZE)
                if data == b"DONE":
                    print(f"[DEBUG] Fragmento {fragment_id} descargado correctamente.")
                    break
                elif data.startswith(b"ERROR"):
                    print(f"[ERROR] {data.decode()}")
                    break
                f.write(data)
        peer.close()

        # Marcar el fragmento como completo
        fragments[fragment_id] = "complete"
        save_progress(file_name, fragments)
    except Exception as e:
        print(f"[ERROR] Error al descargar fragmento {fragment_id}: {e}")

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
    node_id = "NodeA"   # Identificador único para este nodo
    node_port = 8001    # Puerto único para este nodo
    shared_files = ["file1.txt", "file_large.mp4"]  # Archivos compartidos por este nodo

    # Inicia el servidor del nodo en un hilo separado
    threading.Thread(target=start_node_server, args=(node_port,), daemon=True).start()

    # Registra el nodo con el Tracker
    register_with_tracker(node_id, node_port, shared_files)

    # Ejemplo: Descargar un archivo simultáneamente desde múltiples nodos
    file_name_to_download = "file_large.mp4"
    download_file_simultaneously(file_name_to_download)
