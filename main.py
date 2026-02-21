import os
import subprocess
import re
import logging
import asyncio
from typing import List
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel

# Configuración de Logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Viral Video Renderer")

# Directorios
MEDIA_DIR = "/media"
OUTPUT_DIR = "/media" # O /app/output si prefieres separar
OUTPUT_FILENAME = "video_final_viral.mp4"

# --- UTILIDADES ---

def natural_sort_key(s):
    """Permite ordenar p1_1, p1_2, p1_10 correctamente."""
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', s)]

def get_image_files(limit: int = 3) -> List[str]:
    """Obtiene las primeras N imágenes ordenadas numéricamente."""
    files = [f for f in os.listdir(MEDIA_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    files.sort(key=natural_sort_key)
    return files[:limit]

# --- MOTOR DE RENDERIZADO ---

def generate_ffmpeg_command(images: List[str], img_duration: float = 3.0, transition_duration: float = 0.5):
    """
    Construye un comando FFmpeg complejo con Ken Burns y Transiciones Xfade.
    """
    
    inputs = []
    filter_complex = []
    
    # 1. Preparar Inputs y Efecto Ken Burns (Zoom)
    # El zoompan requiere un framerate explícito y duración en frames (25fps * 3s = 75 frames)
    # Añadimos un buffer extra a la duración para asegurar que hay suficiente 'cola' para la transición
    total_frames = int((img_duration + transition_duration) * 30) 
    
    for i, img in enumerate(images):
        inputs.extend(['-loop', '1', '-t', str(img_duration + transition_duration), '-i', os.path.join(MEDIA_DIR, img)])
        
        # Efecto: Zoom suave hacia adentro (1.0 -> 1.15)
        # scale=-1:1920 y crop=1080:1920 aseguran formato vertical perfecto antes del zoom
        filter_complex.append(
            f"[{i}:v]scale=-2:1920,crop=1080:1920:center:center,"
            f"zoompan=z='min(zoom+0.0015,1.2)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,"
            f"format=yuv420p[v{i}]"
        )

    # 2. Encadenar Transiciones (Xfade)
    # Lógica: v0 + v1 -> m1; m1 + v2 -> m2...
    # Xfade offset calculation:
    # Transición 1 empieza en: duration - trans_duration
    # Transición 2 empieza en: (duration - trans_duration) + (duration - trans_duration) ...
    
    current_stream = "[v0]"
    accumulated_time = 0.0
    
    # Lista de transiciones "premium" para rotar
    transitions = ['distance', 'slidedown', 'wiperight', 'circlecrop', 'rectcrop']
    
    for i in range(1, len(images)):
        next_stream = f"[v{i}]"
        output_stream = f"[v_out{i}]" if i < len(images) - 1 else "[video_final]"
        
        # El offset es el tiempo acumulado donde debe empezar la transición
        offset = (img_duration * i) - (transition_duration * i)
        
        # Elegir transición basada en índice (cíclico)
        trans_effect = transitions[(i-1) % len(transitions)]
        
        filter_complex.append(
            f"{current_stream}{next_stream}xfade=transition={trans_effect}:duration={transition_duration}:offset={offset}{output_stream}"
        )
        current_stream = output_stream

    # Unir todo el filtro
    full_filter = ";".join(filter_complex)
    
    # Comando final
    cmd = [
        "ffmpeg",
        "-y", # Sobrescribir
    ]
    
    # Agregar todos los inputs
    cmd.extend(inputs)
    
    # Agregar el filtro complejo
    cmd.extend(["-filter_complex", full_filter])
    
    # Mapear el último stream generado como video salida
    cmd.extend(["-map", "[video_final]"])
    
    # Codecs y optimización
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23", # Calidad visual alta
        "-pix_fmt", "yuv420p", # Compatibilidad máxima
        "-an", # Sin audio por ahora (como solicitado en esta etapa)
        os.path.join(OUTPUT_DIR, OUTPUT_FILENAME)
    ])
    
    return cmd

def run_render_task():
    """Función que ejecuta FFmpeg y maneja errores."""
    logger.info("Iniciando renderizado de video viral...")
    
    try:
        images = get_image_files(limit=3)
        if len(images) < 3:
            logger.error(f"Se requieren al menos 3 imágenes, encontradas: {len(images)}")
            return

        cmd = generate_ffmpeg_command(images, img_duration=3.0, transition_duration=0.7)
        
        logger.info(f"Ejecutando comando FFmpeg: {' '.join(cmd)}")
        
        # Ejecutamos proceso capturando salida para logs
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        if process.returncode != 0:
            logger.error(f"FFmpeg falló:\n{process.stderr}")
        else:
            logger.info(f"Renderizado completado exitosamente: {OUTPUT_FILENAME}")
            
    except Exception as e:
        logger.exception(f"Error crítico durante el renderizado: {e}")

# --- API ENDPOINTS ---

class RenderRequest(BaseModel):
    # Puedes extender esto para recibir parámetros desde n8n
    webhook_url: str = None

@app.get("/")
def health_check():
    return {"status": "online", "service": "Video Renderer"}

@app.post("/render")
async def trigger_render(background_tasks: BackgroundTasks):
    """
    Endpoint para n8n.
    Lanza el proceso en segundo plano y responde rápido.
    """
    # Verificamos que existan archivos
    files = get_image_files()
    if not files:
        raise HTTPException(status_code=404, detail="No se encontraron imágenes en /media")

    # Ejecutamos la tarea pesada en background para no bloquear la request HTTP
    background_tasks.add_task(run_render_task)
    
    return {
        "status": "processing_started",
        "message": "El video se está generando en segundo plano.",
        "assets_found": files
    }

if __name__ == "__main__":
    # Esto es solo para testing local fuera de Docker
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
