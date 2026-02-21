import os
import glob
import logging
import subprocess
import sys

# Configuración de Logging para EasyPanel
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# --- CONFIGURACIÓN DE RUTAS ---
MEDIA_DIR = "/media"
OUTPUT_FILE = os.path.join(MEDIA_DIR, "video_final.mp4")

# Variables de tiempo según el requerimiento del usuario (Test de 3 imágenes)
IMG_VISIBLE_TIME = 3.0  # Segundos reales que se ve cada imagen
TRANSITION_TIME = 0.5   # Segundos de la transición (se solapa)
TOTAL_IMG_DURATION = IMG_VISIBLE_TIME + TRANSITION_TIME
FPS = 30

def get_sorted_images(directory, limit=3):
    """Obtiene y ordena las imágenes alfanuméricamente."""
    search_pattern = os.path.join(directory, "p1_*.png")
    images = glob.glob(search_pattern)
    
    # Ordenamiento lógico: p1_1.png, p1_2.png... p1_10.png
    images.sort(key=lambda x: int(os.path.basename(x).split('_')[1].split('.')[0]))
    
    if len(images) < limit:
        logging.warning(f"Se encontraron solo {len(images)} imágenes, se esperaban {limit}.")
        return images
    
    return images[:limit]

def build_ffmpeg_command():
    images = get_sorted_images(MEDIA_DIR, limit=3)
    if not images:
        logging.error("No se encontraron imágenes en /media. Abortando.")
        sys.exit(1)

    voice_path = os.path.join(MEDIA_DIR, "p1_audio_guion.wav")
    music_path = os.path.join(MEDIA_DIR, "taudio-1.mp3")
    subs_path = os.path.join(MEDIA_DIR, "p1_subtitulos.ass")

    # Verificación de assets críticos
    for path in [voice_path, music_path, subs_path]:
        if not os.path.exists(path):
            logging.error(f"Asset faltante crítico: {path}")
            sys.exit(1)

    num_images = len(images)
    filter_complex = []
    
    # 1. TRATAMIENTO VISUAL Y EFECTO KEN BURNS
    frames_per_img = int(TOTAL_IMG_DURATION * FPS)
    for i in range(num_images):
        # Escala a 9:16 llenando la pantalla sin bordes negros (crop) -> setsar asegura relación de aspecto 1:1 de pixel
        f_scale = f"[{i}:v]format=yuv420p,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[base{i}]"
        
        # Ken Burns: Zoom in continuo y muy sutil (de 1.0 a 1.15) paneando al centro
        f_zoom = f"[base{i}]zoompan=z='min(zoom+0.0015,1.15)':d={frames_per_img}:x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':s=1080x1920:fps={FPS}[z{i}]"
        
        # Aseguramos el formato de pixel correcto después del zoom para que xfade no falle
        f_format = f"[z{i}]format=yuv420p[v{i}]"
        
        filter_complex.extend([f_scale, f_zoom, f_format])

    # 2. TRANSICIONES DE ALTA RETENCIÓN (XFADE)
    # Seleccionamos transiciones modernas y dinámicas
    viral_transitions = ["smoothleft", "distance", "slideright"]
    
    last_out = "v0"
    for i in range(1, num_images):
        offset = i * IMG_VISIBLE_TIME  # Matemáticamente exacto para encadenar
        t_type = viral_transitions[(i-1) % len(viral_transitions)]
        out_node = f"v_trans{i}" if i < num_images - 1 else "v_out"
        
        # xfade combina el output anterior con la imagen actual
        f_xfade = f"[{last_out}][v{i}]xfade=transition={t_type}:duration={TRANSITION_TIME}:offset={offset}[{out_node}]"
        filter_complex.append(f_xfade)
        last_out = out_node

    # 3. HARDBAKING DE SUBTÍTULOS (.ASS)
    # Escapamos la ruta para evitar problemas con el filtro de FFmpeg
    escaped_subs = subs_path.replace("\\", "/").replace(":", "\\:")
    f_subs = f"[{last_out}]ass='{escaped_subs}'[v_final]"
    filter_complex.append(f_subs)

    # 4. TRATAMIENTO DE AUDIO (DUCKING)
    idx_voice = num_images
    idx_music = num_images + 1
    
    # Volumen: Voz al 100%, Música al 7%
    # amix mezcla ambos. duration=longest asegura que la mezcla siga hasta que acabe el más largo
    f_audio = f"[{idx_voice}:a]volume=1.0[voice];[{idx_music}:a]volume=0.07[bgm];[voice][bgm]amix=inputs=2:duration=longest[a_final]"
    filter_complex.append(f_audio)

    # --- CONSTRUCCIÓN DEL COMANDO FFMPEG ---
    cmd = ["ffmpeg", "-y", "-hide_banner"]

    # Añadir inputs de imágenes
    for img in images:
        cmd.extend(["-loop", "1", "-t", str(TOTAL_IMG_DURATION), "-i", img])
    
    # Añadir inputs de audio
    cmd.extend(["-i", voice_path, "-i", music_path])

    # Añadir el grafo de filtros complejos
    cmd.extend(["-filter_complex", ";".join(filter_complex)])

    # Mapeo de salidas y parámetros de codificación para redes sociales
    cmd.extend([
        "-map", "[v_final]",
        "-map", "[a_final]",
        "-c:v", "libx264",
        "-preset", "fast",     # Balance entre velocidad de render en docker y compresión
        "-crf", "23",          # Calidad visual alta
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",           # Corta el video cuando el stream visual termine (9 segundos)
        OUTPUT_FILE
    ])

    return cmd

def run_ffmpeg(cmd):
    logging.info("Iniciando renderizado con FFmpeg...")
    logging.info(f"Comando: {' '.join(cmd)}")
    
    try:
        # Ejecutar ffmpeg, capturar salida para logs de EasyPanel
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=True
        )
        logging.info("¡Renderizado completado con éxito!")
        logging.info(f"Video guardado en: {OUTPUT_FILE}")
    except subprocess.CalledProcessError as e:
        logging.error("Falló la ejecución de FFmpeg.")
        logging.error(f"FFmpeg Output Log:\n{e.stdout}")
        sys.exit(1)
    finally:
        # Limpieza de temporales (Si hubiéramos creado archivos txt intermedios se borrarían aquí)
        pass

if __name__ == "__main__":
    logging.info("Iniciando motor de automatización de video (Modo Transiciones de Alta Retención)...")
    ffmpeg_cmd = build_ffmpeg_command()
    run_ffmpeg(ffmpeg_cmd)
