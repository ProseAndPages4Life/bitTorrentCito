$archivos = "peer.py", "peer_node2.py", "peer_node3.py" # Los nombres de tus archivos
$salidaArchivo = "hashes_comparacion.txt" # Nombre del archivo donde se guardará la salida

# Abre un bloque de script para capturar toda la salida de Write-Host y Write-Warning
# Luego, redirige esa salida al archivo
{
    $hashes = @{}

    foreach ($archivo in $archivos) {
        if (Test-Path $archivo) {
            $hashBytes = Get-FileHash -Path $archivo -Algorithm SHA256 | Select-Object -ExpandProperty Hash
            $base64Hash = [System.Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($hashBytes))
            $hashes[$archivo] = $base64Hash
            Write-Host "Hash (Base64) de '$archivo': $base64Hash"
        } else {
            # Write-Warning por defecto envía a la corriente de error, no a la de éxito.
            # Para capturarlo en Out-File, se puede redirigir o usar Write-Host en su lugar.
            # Aquí lo cambiamos a Write-Host para que aparezca en el archivo.
            Write-Host "AVISO: El archivo '$archivo' no existe y será omitido. Asegúrate de que los archivos estén en el mismo directorio donde ejecutas PowerShell o proporciona la ruta completa."
        }
    }

    Write-Host "`n--- Comparación de Hashes ---`n"

    $valoresHashes = $hashes.Values | Select-Object -Unique

    if ($valoresHashes.Count -eq 1) {
        Write-Host "¡Excelente! Todos los archivos (peer.py, peer_node2.py, peer_node3.py) tienen el **mismo hash Base64**."
    } else {
        Write-Host "Atención: Los archivos tienen **diferentes hashes Base64**."
        Write-Host "Hashes únicos encontrados:"
        $valoresHashes | ForEach-Object { Write-Host "- $_" }
    }
} | Out-File -FilePath $salidaArchivo -Encoding UTF8 -Force