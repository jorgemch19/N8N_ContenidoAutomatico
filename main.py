import os
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip, CompositeAudioClip, CompositeVideoClip

app = FastAPI()
MEDIA_FOLDER = "/media_files"

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

        # 3. Procesar Imágenes con la técnica de "Ventana Rígida"
        img_files = [f for f in os.listdir(MEDIA_FOLDER) 
                     if f.startswith(f"{req.prefix}_") and f.endswith(('.png', '.jpg', '.jpeg'))]
        img_files.sort(key=natural_sort_key)

        num_images = len(img_files)
        base_duration = duration / num_images
        transition_time = 0.5 
        
        # Tamaño fijo para TikTok/Reels
        TARGET_W, TARGET_H = 1080, 1920

        clips = []
        for i, filename in enumerate(img_files):
            path = os.path.join(MEDIA_FOLDER, filename)
            clip_duration = base_duration + transition_time
            
            raw_clip = ImageClip(path)
            
            # PASO A: Escalar la imagen para que CUBRA toda la pantalla + un 15% extra de seguridad
            scale_to_fill = max(TARGET_W / raw_clip.w, TARGET_H / raw_clip.h)
            base_scale = scale_to_fill * 1.15
            base_clip = raw_clip.resize(base_scale)
            
            # PASO B: Aplicar Zoom Dinámico
            zoom_speed = 0.1
            if i % 2 == 0:
                # Zoom IN: De 1.0 (que ya es más grande que la pantalla) a 1.1
                moving_clip = base_clip.resize(lambda t: 1.0 + (zoom_speed * t / clip_duration))
            else:
                # Zoom OUT: De 1.1 a 1.0
                moving_clip = base_clip.resize(lambda t: (1.0 + zoom_speed) - (zoom_speed * t / clip_duration))
            
            # PASO C: El truco final. Meter la imagen que se mueve dentro de una ventana rígida
            # Esto recorta mágicamente los bordes y la mantiene SIEMPRE perfectamente centrada.
            final_clip = CompositeVideoClip(
                [moving_clip.set_position('center')],
                size=(TARGET_W, TARGET_H)
            ).set_duration(clip_duration)
            
            # PASO D: Transición de fundido
            if i > 0:
                final_clip = final_clip.crossfadein(transition_time)
            
            clips.append(final_clip)

        # 4. Unir clips
        video = concatenate_videoclips(clips, method="compose", padding=-transition_time)
        video = video.set_duration(duration)
        video = video.set_audio(final_audio)

        # 5. Renderizado optimizado
        video.write_videofile(
            output_path, 
            fps=30, 
            codec="libx264", 
            audio_codec="aac",
            bitrate="5000k",
            threads=4,
            preset="ultrafast",
            ffmpeg_params=["-vf", f"ass={subs_path}"]
        )

        return {"estado": "ok", "video": req.output_name}

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
