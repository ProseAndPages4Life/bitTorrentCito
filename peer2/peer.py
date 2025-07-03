import socket
import threading
import os
import json
import sys
import time
import shutil # Importar shutil para la copia de archivos

CHUNK_SIZE = 1024 * 1024  # Tamaño de los fragmentos (1 MB)
tracker_ip = "127.0.0.1" # Valor por defecto, se sobrescribe con argumentos
tracker_port = 8000      # Valor por defecto, se sobrescribe con argumentos
progress_file = "progress.json"  # Archivo para guardar el estado de descargas de fragmentos
node_shared_files_db = "node_shared_files.json" # Archivo para guardar la lista de archivos compartidos del nodo

# Variables globales para el nodo actual
current_node_id = None
current_node_port = None
current_shared_files = [] # Esta lista se cargará/guardará y contendrá solo nombres de archivo


def load_shared_files():
    """Carga la lista de nombres de archivos compartidos desde un archivo JSON."""
    peers_dir = os.path.join(os.getcwd(), "peers")
    file_path = os.path.join(peers_dir, node_shared_files_db)
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"[WARNING] Error al leer {node_shared_files_db}. El archivo está corrupto o vacío. Creando uno nuevo.")
            return []
        except Exception as e:
            print(f"[ERROR] Error al cargar {node_shared_files_db}: {e}. Creando uno nuevo.")
            return []
    return []

def save_shared_files(files_list):
    """Guarda la lista de nombres de archivos compartidos en un archivo JSON."""
    peers_dir = os.path.join(os.getcwd(), "peers")
    if not os.path.exists(peers_dir):
        os.makedirs(peers_dir) # Asegurarse de que la carpeta 'peers' exista
    file_path = os.path.join(peers_dir, node_shared_files_db)
    try:
        with open(file_path, 'w') as f:
            json.dump(files_list, f, indent=4)
        print(f"[INFO] Lista de archivos compartidos guardada en {file_path}.")
    except Exception as e:
        print(f"[ERROR] No se pudo guardar la lista de archivos compartidos: {e}")


def register_with_tracker(node_id, node_port, files):
    """
    Registra el nodo con el Tracker, incluyendo el puerto del nodo.
    """
    tracker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        tracker.connect((tracker_ip, tracker_port))
        # Asegurarse de que 'files' sea una lista de nombres de archivos
        files_to_send = [f for f in files if f] # Filtrar cadenas vacías
        tracker.send(f"REGISTER:{node_id}:{node_port}:{':'.join(files_to_send)}".encode())
        response = tracker.recv(1024).decode()
        print(f"Tracker Response: {response}")
    except ConnectionRefusedError:
        print(f"[CRITICAL ERROR] No se pudo conectar al Tracker en {tracker_ip}:{tracker_port}. Asegúrate de que el Tracker esté en ejecución.")
        sys.exit(1) # El peer no puede funcionar sin el tracker
    except Exception as e:
        print(f"[CRITICAL ERROR] Error al registrar con el Tracker: {e}")
        sys.exit(1)
    finally:
        tracker.close()

def request_file(file_name):
    """
    Solicita al Tracker información sobre nodos que tienen el archivo.
    """
    tracker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        tracker.connect((tracker_ip, tracker_port))
        tracker.send(f"REQUEST:{file_name}".encode())
        response = tracker.recv(4096).decode()
        if response.startswith("ERROR"):
            print(f"[ERROR] Tracker devolvió error al solicitar archivo: {response}")
            return []
        return [p for p in response.split(",") if p] # Retorna una lista de nodos en formato 'node_id:ip:port', filtrando vacíos
    except ConnectionRefusedError:
        print(f"[ERROR] No se pudo conectar al Tracker en {tracker_ip}:{tracker_port} para solicitar el archivo.")
        return []
    except Exception as e:
        print(f"[ERROR] Error al solicitar archivo al Tracker: {e}")
        return []
    finally:
        tracker.close()

def request_all_files_from_tracker():
    """
    Solicita al Tracker una lista de todos los archivos que conoce y los peers que los tienen.
    Retorna un diccionario {file_name: [node_id1, node_id2, ...]}
    """
    tracker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    all_available_files = {}
    try:
        tracker.connect((tracker_ip, tracker_port))
        tracker.send(b"LIST_ALL_FILES")
        response = tracker.recv(8192).decode() # Aumentar buffer para muchos archivos
        if response.startswith("ERROR"):
            print(f"[ERROR] Tracker devolvió error al listar archivos: {response}")
            return {}
        
        if response:
            file_entries = response.split(";")
            for entry in file_entries:
                if ":" in entry:
                    file_name, node_ids_str = entry.split(":", 1)
                    node_ids = node_ids_str.split(",")
                    all_available_files[file_name] = node_ids
        return all_available_files
    except ConnectionRefusedError:
        print(f"[ERROR] No se pudo conectar al Tracker en {tracker_ip}:{tracker_port} para listar archivos.")
        return {}
    except Exception as e:
        print(f"[ERROR] Error al solicitar lista de archivos al Tracker: {e}")
        return {}
    finally:
        tracker.close()

def handle_peer_connection(peer_socket):
    """
    Maneja conexiones entrantes desde otros nodos.
    """
    peer_addr = peer_socket.getpeername()
    try:
        data = peer_socket.recv(1024).decode()
        if data.startswith("GET_SIZE"):
            _, file_name = data.split(":")
            print(f"[PEER_SERVER] Recibida solicitud GET_SIZE para '{file_name}' de {peer_addr}")
            send_file_size(peer_socket, file_name)
        elif data.startswith("DOWNLOAD"):
            _, file_name, start, end = data.split(":")
            print(f"[PEER_SERVER] Recibida solicitud DOWNLOAD para '{file_name}' ({start}-{end}) de {peer_addr}")
            send_file_fragment(peer_socket, file_name, int(start), int(end))
        else:
            print(f"[ERROR] Comando no reconocido de {peer_addr}: {data}")
            peer_socket.send(b"ERROR: Comando no reconocido.")
    except ConnectionResetError:
        print(f"[WARNING] Conexión con {peer_addr} reseteada por el cliente.")
    except Exception as e:
        print(f"[ERROR] Error manejando conexión de {peer_addr}: {e}")
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
            print(f"[ERROR_SHARE] El archivo '{file_name}' no existe localmente en {file_path}.")
            peer_socket.send(b"ERROR: Archivo no encontrado.")
            return
        file_size = os.path.getsize(file_path)
        peer_socket.send(f"SIZE:{file_size}".encode())
        print(f"[DEBUG_SHARE] Tamaño de '{file_name}' enviado: {file_size} bytes.")
    except Exception as e:
        print(f"[ERROR_SHARE] Error al enviar tamaño de archivo '{file_name}': {e}")
        peer_socket.send(b"ERROR: Error inesperado al obtener tamanio.")

def send_file_fragment(peer_socket, file_name, start, end):
    """
    Envía un fragmento específico del archivo solicitado.
    """
    try:
        current_dir = os.getcwd()
        file_path = os.path.join(current_dir, "peers", file_name)
        if not os.path.exists(file_path):
            print(f"[ERROR_SHARE] El archivo '{file_name}' no existe localmente en {file_path} para enviar fragmento.")
            peer_socket.send(b"ERROR: Archivo no encontrado para fragmento.")
            return
        with open(file_path, "rb") as f:
            f.seek(start)
            bytes_to_read = end - start + 1
            total_sent = 0
            while bytes_to_read > 0:
                chunk = f.read(min(CHUNK_SIZE, bytes_to_read))
                if not chunk: # End of file reached prematurely or empty chunk
                    break
                peer_socket.send(chunk)
                bytes_to_read -= len(chunk)
                total_sent += len(chunk)
            peer_socket.send(b"DONE") # Signal end of fragment
            print(f"[DEBUG_SHARE] Enviado fragmento {start}-{end} ({total_sent} bytes) de '{file_name}'.")
    except Exception as e:
        print(f"[ERROR_SHARE] Error al enviar fragmento {start}-{end} de '{file_name}': {e}")
        peer_socket.send(b"ERROR: Error inesperado al enviar fragmento.")

def save_progress(file_name, fragments):
    """
    Guarda el progreso de descargas en un archivo JSON.
    """
    try:
        peers_dir = os.path.join(os.getcwd(), "peers")
        if not os.path.exists(peers_dir):
            os.makedirs(peers_dir)

        full_progress_file_path = os.path.join(peers_dir, progress_file)

        progress_data = {}
        if os.path.exists(full_progress_file_path):
            with open(full_progress_file_path, "r") as f:
                try:
                    progress_data = json.load(f)
                except json.JSONDecodeError:
                    print(f"[WARNING] Archivo de progreso {progress_file} corrupto. Iniciando nuevo.")
                    progress_data = {}

        progress_data[file_name] = fragments
        with open(full_progress_file_path, "w") as f:
            json.dump(progress_data, f, indent=4)

        print(f"[INFO_PROGRESS] Progreso guardado para '{file_name}' en {full_progress_file_path}.")
    except Exception as e:
        print(f"[ERROR_PROGRESS] No se pudo guardar el progreso para '{file_name}': {e}")

def load_progress():
    """
    Carga el progreso de descargas desde un archivo JSON.
    """
    try:
        full_progress_file_path = os.path.join(os.getcwd(), "peers", progress_file)
        if os.path.exists(full_progress_file_path):
            with open(full_progress_file_path, "r") as f:
                return json.load(f)
        return {}
    except json.JSONDecodeError:
        print(f"[WARNING] Archivo de progreso {progress_file} corrupto al cargar. Se ignorará el progreso anterior.")
        return {}
    except Exception as e:
        print(f"[ERROR_PROGRESS] No se pudo cargar el progreso: {e}")
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
        elif response.startswith("ERROR:"):
            print(f"[ERROR_DOWNLOAD] Peer {peer_ip}:{peer_port} devolvió error al solicitar tamaño: {response}")
            return None
        else:
            print(f"[ERROR_DOWNLOAD] Respuesta inesperada del peer {peer_ip}:{peer_port} al solicitar tamaño: {response}")
            return None
    except ConnectionRefusedError:
        print(f"[ERROR_DOWNLOAD] No se pudo conectar al peer {peer_ip}:{peer_port}. Podría estar offline o su puerto no está abierto.")
        return None
    except Exception as e:
        print(f"[ERROR_DOWNLOAD] Error al obtener tamaño del archivo '{file_name}' de {peer_ip}:{peer_port}: {e}")
        return None

def download_file_simultaneously(file_name):
    """
    Descarga un archivo completo desde múltiples nodos simultáneamente.
    """
    print(f"\n[DOWNLOAD_MANAGER] Iniciando descarga de '{file_name}'...")
    progress = load_progress()
    fragments_status = progress.get(file_name, {})

    peers_available = request_file(file_name)
    peers_available = [p for p in peers_available if p and len(p.split(':')) == 3] # Limpiar y validar
    
    if not peers_available:
        print(f"[DOWNLOAD_MANAGER] No hay peers disponibles con el archivo '{file_name}'. Descarga cancelada.")
        return

    file_size = None
    for peer_info_str in peers_available:
        try:
            _, peer_ip, peer_port_str = peer_info_str.split(":")
            peer_port = int(peer_port_str)
            file_size = get_file_size(peer_ip, peer_port, file_name)
            if file_size is not None:
                break
        except ValueError:
            print(f"[WARNING] Formato de peer inválido recibido del tracker: {peer_info_str}. Ignorando.")
            continue

    if file_size is None:
        print(f"[DOWNLOAD_MANAGER] No se pudo obtener el tamaño del archivo '{file_name}' de ningún peer. Descarga cancelada.")
        return

    num_fragments = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(f"[DOWNLOAD_MANAGER] '{file_name}' ({file_size} bytes) se dividirá en {num_fragments} fragmentos.")

    all_fragments_info = []
    for i in range(num_fragments):
        start = i * CHUNK_SIZE
        end = min((i + 1) * CHUNK_SIZE - 1, file_size - 1)
        fragment_id = f"{start}-{end}"
        all_fragments_info.append({
            "id": fragment_id,
            "start": start,
            "end": end,
            "status": fragments_status.get(fragment_id, "pending")
        })

    pending_fragments = [f for f in all_fragments_info if f["status"] == "pending"]
    if not pending_fragments:
        print(f"[DOWNLOAD_MANAGER] El archivo '{file_name}' ya está completamente descargado. Verificando combinación...")
        combine_fragments(file_name, all_fragments_info)
        return

    print(f"[DOWNLOAD_MANAGER] Quedan {len(pending_fragments)} fragmentos por descargar.")

    download_threads = []
    
    # Asignar fragmentos a peers disponibles (simple round-robin)
    peer_index = 0
    for frag_info in pending_fragments:
        if not peers_available:
            print("[WARNING] No hay más peers disponibles para descargar fragmentos pendientes. Algunos fragmentos pueden no descargarse.")
            break
        
        peer_info_str = peers_available[peer_index % len(peers_available)]
        try:
            _, peer_ip, peer_port_str = peer_info_str.split(":")
            peer_port = int(peer_port_str)
        except ValueError:
            print(f"[WARNING] Formato de peer inválido en la lista del tracker: {peer_info_str}. Saltando fragmento.")
            peer_index += 1
            continue

        fragment_path = os.path.join(os.getcwd(), "peers", f"{file_name}.part{frag_info['start']}-{frag_info['end']}")
        
        thread = threading.Thread(
            target=download_fragment,
            args=(peer_ip, peer_port, file_name, frag_info['start'], frag_info['end'],
                  fragment_path, frag_info['id'], fragments_status)
        )
        download_threads.append(thread)
        thread.start()
        peer_index += 1

    # Esperar a que todos los hilos de descarga terminen
    for thread in download_threads:
        thread.join()

    # Verificar si todos los fragmentos están completos después de los intentos de descarga
    all_downloaded = True
    for frag_info in all_fragments_info:
        if fragments_status.get(frag_info['id']) != "complete":
            all_downloaded = False
            print(f"[WARNING] Fragmento {frag_info['id']} de '{file_name}' no se descargó completamente.")
            break
    
    if all_downloaded:
        print(f"[DOWNLOAD_MANAGER] Todos los fragmentos de '{file_name}' han sido descargados.")
        combine_fragments(file_name, all_fragments_info)
    else:
        print(f"[DOWNLOAD_MANAGER] La descarga de '{file_name}' no se completó. Algunos fragmentos no pudieron ser obtenidos. Reintenta más tarde.")
        save_progress(file_name, fragments_status) # Guardar el estado actual incluso si incompleto


def download_fragment(peer_ip, peer_port, file_name, start, end, fragment_path, fragment_id, fragments_status):
    """
    Descarga un fragmento específico de un archivo desde un peer.
    """
    try:
        peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        peer_socket.settimeout(10) # Set a timeout for connection and recv operations
        peer_socket.connect((peer_ip, peer_port))
        peer_socket.send(f"DOWNLOAD:{file_name}:{start}:{end}".encode())
        
        received_bytes = 0
        expected_bytes = (end - start + 1)
        
        with open(fragment_path, "wb") as f:
            while received_bytes < expected_bytes:
                data = peer_socket.recv(CHUNK_SIZE)
                if not data: # Connection closed by peer prematurely
                    print(f"[ERROR_FRAGMENT] Peer {peer_ip}:{peer_port} cerró la conexión antes de completar el fragmento {fragment_id} de '{file_name}'.")
                    break
                if data == b"DONE": # Peer signaled end of fragment
                    print(f"[DEBUG_FRAGMENT] Recibido 'DONE' para fragmento {fragment_id} de '{file_name}'.")
                    break
                if data.startswith(b"ERROR"): # Peer sent an error message
                    error_msg = data.decode()
                    print(f"[ERROR_FRAGMENT] Peer {peer_ip}:{peer_port} devolvió error al descargar fragmento {fragment_id} de '{file_name}': {error_msg}")
                    break
                
                f.write(data)
                received_bytes += len(data)
        peer_socket.close()

        if received_bytes >= expected_bytes:
            fragments_status[fragment_id] = "complete"
            save_progress(file_name, fragments_status)
            print(f"[DEBUG_FRAGMENT] Fragmento {fragment_id} de '{file_name}' descargado y verificado ({received_bytes}/{expected_bytes} bytes).")
        else:
            print(f"[WARNING_FRAGMENT] Fragmento {fragment_id} de '{file_name}' de {peer_ip}:{peer_port} no se descargó completamente (Esperado: {expected_bytes}, Recibido: {received_bytes}). Marcado como pendiente.")
            # Asegurarse de que no se marca como completo si no se recibió todo
            if fragments_status.get(fragment_id) == "complete":
                del fragments_status[fragment_id] # Eliminar estado completo si fue parcial
            save_progress(file_name, fragments_status) # Actualizar el progreso con estado pendiente
            # Limpiar el archivo parcial si está incompleto para reintentar desde cero
            try:
                os.remove(fragment_path)
                print(f"[INFO_FRAGMENT] Eliminado fragmento incompleto {fragment_path} para reintento.")
            except OSError as e:
                print(f"[ERROR_FRAGMENT] No se pudo eliminar fragmento incompleto {fragment_path}: {e}")

    except socket.timeout:
        print(f"[ERROR_FRAGMENT] Timeout al conectar o recibir de {peer_ip}:{peer_port} para fragmento {fragment_id} de '{file_name}'.")
    except ConnectionRefusedError:
        print(f"[ERROR_FRAGMENT] Conexión rechazada por {peer_ip}:{peer_port} para fragmento {fragment_id} de '{file_name}'.")
    except Exception as e:
        print(f"[ERROR_FRAGMENT] Error inesperado al descargar fragmento {fragment_id} de '{file_name}' de {peer_ip}:{peer_port}: {e}")

def combine_fragments(file_name, all_fragments_info):
    """
    Combina los fragmentos descargados en un archivo completo.
    """
    peers_dir = os.path.join(os.getcwd(), "peers")
    combined_path = os.path.join(peers_dir, f"downloaded_{file_name}")
    
    # Ordenar los fragmentos por su rango inicial para combinarlos correctamente
    all_fragments_info.sort(key=lambda x: x['start'])

    try:
        with open(combined_path, "wb") as outfile:
            for frag_info in all_fragments_info:
                fragment_path = os.path.join(peers_dir, f"{file_name}.part{frag_info['start']}-{frag_info['end']}")
                if os.path.exists(fragment_path):
                    with open(fragment_path, "rb") as infile:
                        outfile.write(infile.read())
                    os.remove(fragment_path) # Eliminar el fragmento después de combinar
                else:
                    print(f"[WARNING] Fragmento {fragment_path} no encontrado para combinar. El archivo final podría estar incompleto.")
        print(f"[INFO_COMBINE] Archivo '{file_name}' descargado y combinado correctamente en {combined_path}.")
        # Opcional: Eliminar la entrada de progreso del archivo una vez combinado completamente
        progress = load_progress()
        if file_name in progress:
            del progress[file_name]
            save_progress(file_name, progress) # Guardar el progreso sin el archivo completo
            print(f"[INFO_COMBINE] Progreso de '{file_name}' eliminado.")
    except Exception as e:
        print(f"[ERROR_COMBINE] Error al combinar los fragmentos de '{file_name}': {e}")


def start_node_server(node_port):
    """
    Inicia un servidor para escuchar solicitudes entrantes desde otros nodos.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # Permite reusar la dirección rápidamente
    try:
        server.bind(("0.0.0.0", node_port))
        server.listen(5)
        print(f"Servidor del nodo ejecutándose en el puerto {node_port}")

        while True:
            peer_socket, addr = server.accept()
            threading.Thread(target=handle_peer_connection, args=(peer_socket,)).start()
    except OSError as e:
        if e.errno == 98: # Address already in use
            print(f"[CRITICAL ERROR] El puerto {node_port} ya está en uso. Por favor, especifique un puerto diferente.")
        else:
            print(f"[CRITICAL ERROR] Error al iniciar el servidor del nodo en el puerto {node_port}: {e}")
        sys.exit(1) # Salir si el servidor no puede iniciarse
    except Exception as e:
        print(f"[CRITICAL ERROR] Error inesperado al iniciar el servidor del nodo: {e}")
        sys.exit(1)

# Función para añadir un archivo a la lista de compartidos y registrarlo
def share_new_file():
    """
    Permite al usuario ingresar la ruta de un archivo para compartir.
    """
    global current_shared_files, current_node_id, current_node_port

    file_path_input = input("Introduce la RUTA COMPLETA del archivo que deseas compartir: ").strip()
    
    if not os.path.exists(file_path_input):
        print(f"[ERROR_SHARE_MENU] El archivo '{file_path_input}' no existe.")
        return

    file_name = os.path.basename(file_path_input)
    
    peers_dir = os.path.join(os.getcwd(), "peers")
    destination_path = os.path.join(peers_dir, file_name)

    # Solo copiar si el archivo no está ya en la carpeta 'peers'
    if os.path.abspath(file_path_input) != os.path.abspath(destination_path):
        try:
            shutil.copy(file_path_input, destination_path)
            print(f"[INFO_SHARE_MENU] Archivo '{file_name}' copiado a la carpeta de peers.")
        except Exception as e:
            print(f"[ERROR_SHARE_MENU] No se pudo copiar el archivo a la carpeta de peers: {e}")
            return
    else:
        print(f"[INFO_SHARE_MENU] El archivo '{file_name}' ya está en la carpeta de peers.")

    if file_name not in current_shared_files:
        current_shared_files.append(file_name)
        save_shared_files(current_shared_files) # Guardar la lista actualizada en el archivo de persistencia
        print(f"[INFO_SHARE_MENU] Registrando '{file_name}' con el Tracker...")
        register_with_tracker(current_node_id, current_node_port, current_shared_files)
    else:
        print(f"[INFO_SHARE_MENU] '{file_name}' ya está siendo compartido.")

# Función para mostrar los archivos disponibles y permitir la selección para descargar
def download_menu():
    """
    Muestra los archivos disponibles en la red y permite al usuario elegir uno para descargar.
    """
    while True:
        print("\n--- Archivos Disponibles para Descargar ---")
        
        available_files_from_tracker = request_all_files_from_tracker()
        
        if not available_files_from_tracker:
            print("[INFO_DOWNLOAD_MENU] No hay archivos disponibles registrados en el Tracker en este momento.")
            print("[R] Regresar al menú anterior")
            choice = input("Elige una opción: ").strip().lower()
            if choice == 'r':
                return
            else:
                print("[ERROR_DOWNLOAD_MENU] Opción inválida.")
                continue

        # Convertir el diccionario de archivos a una lista ordenada para mostrar
        file_names_list = sorted(available_files_from_tracker.keys())
        
        for i, file_name in enumerate(file_names_list):
            nodes_sharing = available_files_from_tracker[file_name]
            print(f"[{i+1}] {file_name} (Compartido por: {', '.join(sorted(nodes_sharing))})") # Ordenar por nodo para consistencia
        
        print("[R] Regresar al menú anterior")
        
        choice = input("Introduce el número del archivo que deseas descargar (o 'r' para regresar): ").strip().lower()
        
        if choice == 'r':
            return # Regresar al menú principal
        
        try:
            index = int(choice) - 1
            if 0 <= index < len(file_names_list):
                file_to_download = file_names_list[index]
                # Antes de descargar, verificar si el archivo ya está descargado y combinado
                downloaded_file_path = os.path.join(os.getcwd(), "peers", f"downloaded_{file_to_download}")
                if os.path.exists(downloaded_file_path):
                    print(f"[INFO_DOWNLOAD_MENU] El archivo '{file_to_download}' ya parece estar descargado en '{downloaded_file_path}'.")
                    # Ofrecer re-descargar o simplemente regresar
                    re_download = input("¿Deseas intentar descargarlo de nuevo? (s/n): ").strip().lower()
                    if re_download != 's':
                        continue # Volver al menú de descarga
                    else:
                        # Si decide re-descargar, limpiar el progreso anterior
                        progress = load_progress()
                        if file_to_download in progress:
                            del progress[file_to_download]
                            save_progress(file_to_download, progress)
                            print(f"[INFO_DOWNLOAD_MENU] Limpiado progreso anterior para '{file_to_download}'.")
                        # También eliminar archivos parciales existentes para evitar conflictos
                        for f_name in os.listdir(os.path.join(os.getcwd(), "peers")):
                            if f_name.startswith(f"{file_to_download}.part"):
                                try:
                                    os.remove(os.path.join(os.getcwd(), "peers", f_name))
                                    print(f"[INFO_DOWNLOAD_MENU] Eliminado fragmento antiguo: {f_name}")
                                except OSError as e:
                                    print(f"[WARNING_DOWNLOAD_MENU] No se pudo eliminar fragmento antiguo {f_name}: {e}")


                print(f"[INFO_DOWNLOAD_MENU] Iniciando descarga de '{file_to_download}'...")
                # La función download_file_simultaneously se encargará de encontrar los peers
                # y descargar los fragmentos.
                download_file_simultaneously(file_to_download)
                return # Regresar al menú principal después de intentar descargar
            else:
                print("[ERROR_DOWNLOAD_MENU] Número fuera de rango. Por favor, elige un número válido.")
        except ValueError:
            print("[ERROR_DOWNLOAD_MENU] Opción inválida. Introduce un número o 'r'.")
        except Exception as e:
            print(f"[ERROR_DOWNLOAD_MENU] Error inesperado en el menú de descarga: {e}")

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    # Uso: python peer.py <tracker_ip> <tracker_port> <node_id> <node_port> [initial_shared_files_comma_separated]

    if len(sys.argv) < 5:
        print("Uso: python peer.py <tracker_ip> <tracker_port> <node_id> <node_port> [initial_shared_files_comma_separated]")
        print("Ejemplo: python peer.py 127.0.0.1 8000 NodeA 8001 file1.txt,file_large.mp4")
        print("         Para un nodo que solo inicia sin archivos compartidos: python peer.py 127.0.0.1 8000 NodeX 8004 ''")
        sys.exit(1)

    try:
        tracker_ip = sys.argv[1]
        tracker_port = int(sys.argv[2])
        current_node_id = sys.argv[3] # Asignar a la global
        current_node_port = int(sys.argv[4]) # Asignar a la global
        
        initial_shared_files_from_args = []
        if len(sys.argv) > 5 and sys.argv[5] != "''": # Permite pasar '' para shared_files vacíos
            initial_shared_files_str = sys.argv[5]
            initial_shared_files_from_args = [f.strip() for f in initial_shared_files_str.split(',') if f.strip()]

        print(f"[INFO] Iniciando {current_node_id}...")
        print(f"[INFO] Tracker: {tracker_ip}:{tracker_port}")
        print(f"[INFO] Puerto del Nodo: {current_node_port}")
        
    except ValueError:
        print("[ERROR] El puerto del Tracker y el puerto del Nodo deben ser números enteros.")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Error al parsear argumentos: {e}")
        sys.exit(1)
        
    # Crear la carpeta 'peers' si no existe
    peers_dir = os.path.join(os.getcwd(), "peers")
    if not os.path.exists(peers_dir):
        os.makedirs(peers_dir)
        print(f"[INFO] Creada la carpeta de peers: {peers_dir}")

    # Cargar los archivos compartidos existentes (persistencia)
    current_shared_files = load_shared_files()
    
    # Combinar archivos iniciales de argumentos con archivos persistentes
    for file_name in initial_shared_files_from_args:
        if file_name not in current_shared_files:
            # Verificar si el archivo existe físicamente en la carpeta 'peers' antes de agregarlo
            file_path_in_peers = os.path.join(peers_dir, file_name)
            if os.path.exists(file_path_in_peers):
                current_shared_files.append(file_name)
                print(f"[INFO] '{file_name}' agregado a la lista de archivos compartidos desde el inicio.")
            else:
                print(f"[WARNING] El archivo '{file_name}' (especificado en argumentos) no existe en la carpeta '{peers_dir}'. No se registrará.")

    save_shared_files(current_shared_files) # Guardar la lista consolidada (persistencia + argumentos válidos)

    print(f"[INFO] Archivos compartidos iniciales del nodo: {current_shared_files if current_shared_files else 'Ninguno'}")


    # Inicia el servidor del nodo en un hilo separado
    threading.Thread(target=start_node_server, args=(current_node_port,), daemon=True).start()
    time.sleep(0.5) # Pequeña pausa para asegurar que el servidor se esté levantando

    # Registra el nodo con el Tracker con la lista consolidada de archivos
    register_with_tracker(current_node_id, current_node_port, current_shared_files)

    # Bucle principal de menú interactivo
    while True:
        print("\n--- Menú Principal del Nodo ---")
        print("1. Compartir un archivo (subir)")
        print("2. Descargar un archivo")
        print("3. Salir")
        
        main_choice = input("Elige una opción: ").strip()

        if main_choice == '1':
            share_new_file() # Ahora no necesita pasar argumentos, usa las globales
        elif main_choice == '2':
            download_menu() # Ahora no necesita pasar argumentos, usa las globales
        elif main_choice == '3':
            print(f"[INFO] {current_node_id} saliendo...")
            break
        else:
            print("[ERROR] Opción inválida. Por favor, elige 1, 2 o 3.")

    print("[INFO] Programa del nodo finalizado.")
    sys.exit(0)