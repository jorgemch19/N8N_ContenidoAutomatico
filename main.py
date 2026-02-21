import os
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip, CompositeAudioClip, afx

app = FastAPI()
MEDIA_FOLDER = "/media"

class VideoRequest(BaseModel):
    prefix: str
    output_name: str
    audio_bg: str = "taudio-1.mp3" # Valor por defecto

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', s)]

@app.post("/crear-video")
def crear_video(req: VideoRequest):
    try:
        # 1. Rutas de archivos
        audio_main_path = os.path.join(MEDIA_FOLDER, f"{req.prefix}_audio_guion.mp3")
        # Si no existe mp3, probamos wav
        if not os.path.exists(audio_main_path):
            audio_main_path = audio_main_path.replace(".mp3", ".wav")
            
        bg_music_path = os.path.join(MEDIA_FOLDER, req.audio_bg)
        subs_path = os.path.join(MEDIA_FOLDER, f"{req.prefix}_subtitulos.ass")
        output_path = os.path.join(MEDIA_FOLDER, req.output_name)

        # 2. Cargar Audio Principal y medir duración
        if not os.path.exists(audio_main_path):
            raise HTTPException(status_code=404, detail=f"No falta audio guion en {audio_main_path}")
        
        main_audio = AudioFileClip(audio_main_path)
        duration = main_audio.duration

        # 3. Cargar Audio de Fondo (loop y volumen bajo)
        if os.path.exists(bg_music_path):
            bg_audio = AudioFileClip(bg_music_path).volumex(0.1) # Volumen al 10%
            # Hacer que el fondo dure lo mismo que el principal
            bg_audio = bg_audio.set_duration(duration)
            final_audio = CompositeAudioClip([main_audio, bg_audio])
        else:
            final_audio = main_audio

        # 4. Procesar Imágenes
        search_pattern = f"{req.prefix}_"
        img_files = [f for f in os.listdir(MEDIA_FOLDER) 
                     if f.startswith(search_pattern) and f.endswith(('.png', '.jpg', '.jpeg'))]
        img_files.sort(key=natural_sort_key)

        if not img_files:
            raise HTTPException(status_code=404, detail="No se encontraron imágenes")

        # Calcular cuánto dura cada imagen para llenar el tiempo del audio
        duration_per_img = duration / len(img_files)

        clips = [ImageClip(os.path.join(MEDIA_FOLDER, f)).set_duration(duration_per_img) for f in img_files]
        video = concatenate_videoclips(clips, method="compose")
        video = video.set_audio(final_audio)

        # 5. Renderizar con Subtítulos (Usando filtro de FFmpeg)
        # Nota: La ruta de los subs en el filtro debe ser absoluta dentro del contenedor
        # Para que FFmpeg no se líe con las rutas en Linux, usamos este formato:
        video.write_videofile(
            output_path, 
            fps=24, 
            codec="libx264", 
            audio_codec="aac",
            ffmpeg_params=["-vf", f"ass={subs_path}"]
        )

        return {"estado": "ok", "video": req.output_name, "duracion": duration}

    except Exception as e:
        print(f"ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
