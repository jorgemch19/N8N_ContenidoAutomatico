import os
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip, CompositeAudioClip

app = FastAPI()
MEDIA_FOLDER = "/media"

class VideoRequest(BaseModel):
    prefix: str
    output_name: str
    audio_bg: str = "taudio-1.mp3"

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', s)]

@app.post("/crear-video")
def crear_video(req: VideoRequest):
    try:
        # 1. Configuración de rutas
        audio_main_path = os.path.join(MEDIA_FOLDER, f"{req.prefix}_audio_guion.mp3")
        if not os.path.exists(audio_main_path):
            audio_main_path = audio_main_path.replace(".mp3", ".wav")
            
        bg_music_path = os.path.join(MEDIA_FOLDER, req.audio_bg)
        subs_path = os.path.join(MEDIA_FOLDER, f"{req.prefix}_subtitulos.ass")
        output_path = os.path.join(MEDIA_FOLDER, req.output_name)

        # 2. Audio
        main_audio = AudioFileClip(audio_main_path)
        duration = main_audio.duration
        
        if os.path.exists(bg_music_path):
            bg_audio = AudioFileClip(bg_music_path).volumex(0.1).set_duration(duration)
            final_audio = CompositeAudioClip([main_audio, bg_audio])
        else:
            final_audio = main_audio

        # 3. Procesar Imágenes con efecto Zoom
        img_files = [f for f in os.listdir(MEDIA_FOLDER) 
                     if f.startswith(f"{req.prefix}_") and f.endswith(('.png', '.jpg', '.jpeg'))]
        img_files.sort(key=natural_sort_key)

        num_images = len(img_files)
        # Duración base de cada imagen
        base_duration = duration / num_images
        # Tiempo de transición (crossfade)
        transition_time = 0.5 

        clips = []
        for i, filename in enumerate(img_files):
            path = os.path.join(MEDIA_FOLDER, filename)
            
            # Crear clip. Le sumamos el tiempo de transición para que se solapen sin acortar el video
            clip = ImageClip(path).set_duration(base_duration + transition_time)
            
            # --- EFECTO ZOOM (Para estilo viral) ---
            # Escala de 1.0 a 1.2 (un zoom del 20%)
            clip = clip.resize(lambda t: 1 + 0.02 * t) 
            
            # --- TRANSICIÓN ---
            if i > 0:
                clip = clip.crossfadein(transition_time)
            
            clips.append(clip)

        # 4. Unir clips con solapamiento (padding negativo hace que se encabalguen)
        video = concatenate_videoclips(clips, method="compose", padding=-transition_time)
        
        # Ajustar duración exacta para que no sobren milisegundos
        video = video.set_duration(duration)
        video = video.set_audio(final_audio)

        # 5. Renderizado final con subtítulos quemados
        video.write_videofile(
            output_path, 
            fps=30, # 30 fps para más fluidez en TikTok
            codec="libx264", 
            audio_codec="aac",
            ffmpeg_params=["-vf", f"ass={subs_path}"]
        )

        return {"estado": "ok", "video": req.output_name, "duracion": duration}

    except Exception as e:
        print(f"ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
