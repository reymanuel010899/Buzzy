import subprocess
import json


def extract_geolocation_from_video(video_path: str) -> dict:
    """
    Extrae metadatos de geolocalización de un video MP4 usando exiftool.
    Retorna un diccionario con latitude, longitude, y otros metadatos relevantes.
    """
    try:
        # Comando exiftool para extraer metadatos embebidos (-ee) en formato JSON (-j)
        command = [
            'exiftool',
            '-ee',  # Extraer metadatos embebidos
            '-j',   # Salida en formato JSON
            '-n',   # Números en formato decimal (sin grados, minutos, segundos)
            video_path
        ]

        # Ejecutar el comando y capturar la salida
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        metadata = json.loads(result.stdout)[0]  # Parsear JSON, asumiendo un solo archivo

        # Extraer geolocalización si existe
        latitude = metadata.get('GPSLatitude', None)
        longitude = metadata.get('GPSLongitude', None)

        if latitude and longitude:
            return {
                'latitude': float(latitude),
                'longitude': float(longitude),
                'other_metadata': {k: v for k, v in metadata.items() if k not in ['SourceFile', 'ExifTool:ExifToolVersion']}
            }
        return {'latitude': None, 'longitude': None, 'other_metadata': metadata}

    except subprocess.CalledProcessError as e:
        print(f"Error al ejecutar exiftool: {e.stderr}")
        return {'latitude': None, 'longitude': None, 'error': str(e)}
    except json.JSONDecodeError as e:
        print(f"Error al parsear JSON: {e}")
        return {'latitude': None, 'longitude': None, 'error': str(e)}

