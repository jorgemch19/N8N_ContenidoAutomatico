import os
import subprocess
import re
import logging
import time
from typing import List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Configuración de Logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Viral Video Renderer")

# Directorios
MEDIA_DIR = "/media"
OUTPUT_FILENAME = "video_final_viral.mp4"
OUTPUT_PATH = os.path.join(MEDIA_DIR, OUTPUT_FILENAME)

# --- UTILIDADES ---

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]

def get_image_files(limit: int = 3) -> List[str]:
    files = [f for f in os.listdir(MEDIA_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    files.sort(key=natural_sort_key)
    return files[:limit]

# --- MOTOR DE RENDERIZADO ---

def run_ffmpeg_render(images: List[str]):
    """
    Ejecuta FFmpeg de forma BLOQUEANTE. 
    Lanza excepción si falla.
    """
    
    # Parámetros de tiempo
    # Duración base de visualización por imagen (sin contar transición)
    display_time = 3.0 
    # Duración de la transición
    trans_duration = 0.75 
    # Duración total del clip de cada imagen (debe ser más largo para permitir solapamiento)
    clip_duration = display_time + trans_duration 
    
    fps = 30
    total_frames_per_clip = int(clip_duration * fps)

    # Construcción del comando
    inputs = []
    filter_complex = []
    
    # 1. Crear inputs y filtros de Ken Burns
    for i, img in enumerate(images):
        path = os.path.join(MEDIA_DIR, img)
        inputs.extend(['-loop', '1', '-t', str(clip_duration), '-i', path])
        
        # EXPLICACIÓN TÉCNICA DEL FIX (Para evitar 0KB):
        # 1. scale+crop: Asegura tamaño.
        # 2. zoompan: Hace el zoom. Importante: d=... establece duración en frames.
        # 3. trim=duration: OBLIGA a cortar el stream, evitando bucles infinitos.
        # 4. setpts=PTS-STARTPTS: Resetea el reloj interno del video para que empiece en 0.
        
        filter_complex.append(
            f"[{i}:v]"
            f"scale=-2:1920,crop=1080:1920:center:center,"
            f"zoompan=z='min(zoom+0.0015,1.2)':d={total_frames_per_clip}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps},"
            f"trim=duration={clip_duration},"
            f"setpts=PTS-STARTPTS,"
            f"format=yuv420p"
            f"[v{i}]"
        )

    # 2. Transiciones (Xfade)
    # El offset es crucial. Si imagen 1 dura 3.75s y transición es 0.75s:
    # La transición debe empezar en el segundo 3.0 (3.75 - 0.75).
    
    current_stream = "[v0]"
    transitions_list = ['distance', 'slidedown', 'wiperight', 'circlecrop', 'rectcrop']
    
    # Acumulador para saber dónde empieza la siguiente transición
    # La primera imagen dura 'display_time' sola antes de empezar a transicionar
    accumulated_offset = display_time 
    
    for i in range(1, len(images)):
        next_stream = f"[v{i}]"
        output_stream = f"[v_out{i}]" if i < len(images) - 1 else "[video_final]"
        
        trans_effect = transitions_list[(i-1) % len(transitions_list)]
        
        filter_complex.append(
            f"{current_stream}{next_stream}xfade=transition={trans_effect}:duration={trans_duration}:offset={accumulated_offset}{output_stream}"
        )
        
        current_stream = output_stream
        accumulated_offset += display_time # Sumamos 3 segundos para la siguiente

    full_filter = ";".join(filter_complex)
    
    cmd = [
        "ffmpeg", "-y",
    ]
    cmd.extend(inputs)
    cmd.extend(["-filter_complex", full_filter])
    cmd.extend(["-map", "[video_final]"])
    cmd.extend([
        "-c:v", "libx264", 
        "-preset", "ultrafast", # Para pruebas rápidas. Cambiar a 'medium' para producción
        "-crf", "23", 
        "-pix_fmt", "yuv420p", 
        "-an", # Sin audio por ahora
        OUTPUT_PATH
    ])
    
    logger.info(f"Comando generado: {' '.join(cmd)}")
    
    # EJECUCIÓN SÍNCRONA (ESPERA AQUI)
    try:
        # Timeout de 120 segundos para evitar bloqueos infinitos
        process = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True,
            timeout=120 
        )
        
        if process.returncode != 0:
            logger.error(f"FFmpeg Error Log:\n{process.stderr}")
            raise Exception("FFmpeg falló al renderizar.")
            
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg tardó demasiado y fue cancelado.")
        raise Exception("Timeout en renderizado.")

    # Verificar que el archivo existe y pesa más de 0
    if not os.path.exists(OUTPUT_PATH) or os.path.getsize(OUTPUT_PATH) == 0:
        raise Exception("El archivo de salida es 0 KB o no existe.")

    return True

# --- API ENDPOINTS ---

@app.post("/render")
def trigger_render():
    """
    Endpoint BLOQUEANTE.
    n8n esperará aquí hasta que return entregue el JSON.
    """
    start_time = time.time()
    logger.info("Recibida petición de renderizado (Síncrono)")
    
    try:
        images = get_image_files(limit=3)
        if len(images) < 3:
            raise HTTPException(status_code=400, detail=f"Se necesitan 3 imágenes, encontradas: {len(images)}")

        # Borrar video anterior si existe
        if os.path.exists(OUTPUT_PATH):
            os.remove(OUTPUT_PATH)

        # Esta función detiene la ejecución del código hasta que FFmpeg termina
        run_ffmpeg_render(images)
        
        elapsed = round(time.time() - start_time, 2)
        logger.info(f"Renderizado finalizado en {elapsed} segundos.")
        
        return {
            "status": "success",
            "message": "Video generado correctamente",
            "file_path": OUTPUT_PATH,
            "execution_time": f"{elapsed}s",
            "video_size_mb": round(os.path.getsize(OUTPUT_PATH) / (1024*1024), 2)
        }

    except Exception as e:
        logger.error(f"Error en endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
