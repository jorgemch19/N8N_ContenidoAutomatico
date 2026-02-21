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
        # 1. Rutas
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

        # 3. Procesar Imágenes con Zoom Dinámico
        img_files = [f for f in os.listdir(MEDIA_FOLDER) 
                     if f.startswith(f"{req.prefix}_") and f.endswith(('.png', '.jpg', '.jpeg'))]
        img_files.sort(key=natural_sort_key)

        num_images = len(img_files)
        base_duration = duration / num_images
        transition_time = 0.6  # Un poco más de transición para que se vea suave

        clips = []
        for i, filename in enumerate(img_files):
            path = os.path.join(MEDIA_FOLDER, filename)
            
            # Cada clip dura su tiempo base + el solapamiento de la transición
            clip_duration = base_duration + transition_time
            clip = ImageClip(path).set_duration(clip_duration)
            
            # --- EFECTO ZOOM ALTERNADO (In/Out) ---
            zoom_speed = 0.1 # Nivel de zoom (10%)
            
            if i % 2 == 0:
                # IMAGEN PAR: Zoom In (1.0 -> 1.1)
                clip = clip.resize(lambda t: 1 + (zoom_speed * t / clip_duration))
            else:
                # IMAGEN IMPAR: Zoom Out (1.1 -> 1.0)
                clip = clip.resize(lambda t: (1 + zoom_speed) - (zoom_speed * t / clip_duration))
            
            # Aplicar transición de entrada (excepto al primero)
            if i > 0:
                clip = clip.crossfadein(transition_time)
            
            clips.append(clip)

        # 4. Unir clips con padding negativo para el fundido
        video = concatenate_videoclips(clips, method="compose", padding=-transition_time)
        video = video.set_duration(duration)
        video = video.set_audio(final_audio)

        # 5. Renderizar con Subtítulos
        video.write_videofile(
            output_path, 
            fps=30, 
            codec="libx264", 
            audio_codec="aac",
            temp_audiofile="/tmp/temp-audio.m4a", # Archivo temporal de audio
            remove_temp=True,
            ffmpeg_params=["-vf", f"ass={subs_path}"]
        )

        return {"estado": "ok", "video": req.output_name}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
``
