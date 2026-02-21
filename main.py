from fastapi import FastAPI, HTTPException
import subprocess
import os
import glob
import re

app = FastAPI()

MEDIA_DIR = "/media"
OUTPUT_FILE = os.path.join(MEDIA_DIR, "video_final.mp4")

@app.post("/generate")
def generate_video():
    """
    Endpoint para ser llamado desde n8n.
    Busca 3 imágenes, aplica Ken Burns, transiciones xfade, 
    audio ducking y hardbakes de subtítulos.
    """
    
    # 1. Búsqueda y ordenación natural de imágenes (1, 2, 3...)
    image_files = glob.glob(os.path.join(MEDIA_DIR, "p1_*.png"))
    
    def extract_number(filename):
        match = re.search(r'p1_(\d+)\.png', filename)
        return int(match.group(1)) if match else 0
        
    image_files.sort(key=extract_number)
    images = image_files[:3] # Tomar estrictamente las 3 primeras

    if len(images) < 3:
        raise HTTPException(status_code=400, detail="No hay suficientes imágenes. Se requieren al menos 3 en /media.")

    # 2. Rutas de Audio y Subtítulos
    voice_audio = os.path.join(MEDIA_DIR, "p1_audio_guion.wav")
    bgm_audio = os.path.join(MEDIA_DIR, "taudio-1.mp3")
    subs_file = os.path.join(MEDIA_DIR, "p1_subtitulos.ass")
    
    has_voice = os.path.exists(voice_audio)
    has_bgm = os.path.exists(bgm_audio)
    has_subs = os.path.exists(subs_file)

    # 3. Construcción del Filtergraph (El núcleo de la magia visual)
    # Explicación de matemática: 3 segundos a 30fps = 90 frames (d=90).
    # Las transiciones duran 0.5s. Img1 (0 a 3s), Img2 entra en 2.5s, Img3 entra en 5.0s. 
    # Total de video: 8.0 segundos.
    
    filter_complex = f"""
    [0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[v0_s];
    [v0_s]zoompan=z='1.0+0.0015*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=90:fps=30:s=1080x1920,format=yuv420p[v0];
    
    [1:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[v1_s];
    [v1_s]zoompan=z='1.09-0.0015*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=90:fps=30:s=1080x1920,format=yuv420p[v1];
    
    [2:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[v2_s];
    [v2_s]zoompan=z='1.05':x='x+1':y='ih/2-(ih/zoom/2)':d=90:fps=30:s=1080x1920,format=yuv420p[v2];
    
    [v0][v1]xfade=transition=smoothleft:duration=0.5:offset=2.5[x1];
    [x1][v2]xfade=transition=smoothdown:duration=0.5:offset=5.0[vout_video];
    """
    
    current_video_label = "[vout_video]"

    # 4. Inserción de Subtítulos (.ass) en el stream visual
    if has_subs:
        # Importante: Como ejecutamos ffmpeg en cwd=MEDIA_DIR, solo pasamos el nombre del archivo
        subs_filename = os.path.basename(subs_file)
        filter_complex += f"{current_video_label}ass='{subs_filename}'[vout_final];\n"
        current_video_label = "[vout_final]"

    # 5. Tratamiento de Audio (Ducking 100% voz / 7% BGM)
    # Los índices de entrada de audio dependerán de si existen.
    # [0,1,2] son imágenes. Voice será [3], BGM será [4].
    if has_voice and has_bgm:
        filter_complex += "[3:a]volume=1.0[a_v]; [4:a]volume=0.07[a_b]; [a_v][a_b]amix=inputs=2:duration=first:dropout_transition=2[aout];\n"
        current_audio_label = "[aout]"
    elif has_voice:
        filter_complex += "[3:a]volume=1.0[aout];\n"
        current_audio_label = "[aout]"
    elif has_bgm:
        filter_complex += "[3:a]volume=0.07[aout];\n"
        current_audio_label = "[aout]"
    else:
        current_audio_label = None

    # 6. Ensamblado del Comando FFmpeg
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", "3", "-i", images[0],
        "-loop", "1", "-t", "3", "-i", images[1],
        "-loop", "1", "-t", "3", "-i", images[2],
    ]
    
    if has_voice: cmd.extend(["-i", voice_audio])
    if has_bgm:   cmd.extend(["-i", bgm_audio])
    
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", current_video_label
    ])
    
    if current_audio_label:
        cmd.extend(["-map", current_audio_label])
        
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", "8.0",  # Fuerza el renderizado a 8 segundos exactos
        OUTPUT_FILE
    ])

    # 7. Ejecución de proceso Headless
    try:
        # cwd=MEDIA_DIR es crítico para que el filtro ass= encuentre la fuente
        subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=MEDIA_DIR)
        
        # Limpieza opcional de imágenes si se requiere no acumular basura (descomentar)
        # for img in images: os.remove(img)
            
        return {
            "status": "success",
            "message": "Video viral generado exitosamente",
            "file": OUTPUT_FILE,
            "duration": "8.0s"
        }
        
    except subprocess.CalledProcessError as e:
        # Captura y muestra los logs nativos de C++ de FFmpeg para fácil debugging en EasyPanel
        error_msg = f"FFmpeg failed. \nStdout: {e.stdout} \nStderr: {e.stderr}"
        print(error_msg) 
        raise HTTPException(status_code=500, detail="Error en procesamiento multimedia. Revisa los logs del contenedor.")
