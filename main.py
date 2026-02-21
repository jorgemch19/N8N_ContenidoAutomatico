import os
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip, CompositeAudioClip
import moviepy.video.fx.all as vfx

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
        # 1. Rutas y Archivos
        audio_main_path = os.path.join(MEDIA_FOLDER, f"{req.prefix}_audio_guion.mp3")
        if not os.path.exists(audio_main_path):
            audio_main_path = audio_main_path.replace(".mp3", ".wav")
            
        bg_music_path = os.path.join(MEDIA_FOLDER, req.audio_bg)
        subs_path = os.path.join(MEDIA_FOLDER, f"{req.prefix}_subtitulos.ass")
        output_path = os.path.join(MEDIA_FOLDER, req.output_name)

        # 2. Cargar Audio
        main_audio = AudioFileClip(audio_main_path)
        duration = main_audio.duration
        
        if os.path.exists(bg_music_path):
            bg_audio = AudioFileClip(bg_music_path).volumex(0.1).set_duration(duration)
            final_audio = CompositeAudioClip([main_audio, bg_audio])
        else:
            final_audio = main_audio

        # 3. Procesar Imágenes
        img_files = [f for f in os.listdir(MEDIA_FOLDER) 
                     if f.startswith(f"{req.prefix}_") and f.endswith(('.png', '.jpg', '.jpeg'))]
        img_files.sort(key=natural_sort_key)

        num_images = len(img_files)
        base_duration = duration / num_images
        transition_time = 0.5 

        clips = []
        for i, filename in enumerate(img_files):
            path = os.path.join(MEDIA_FOLDER, filename)
            
            # Cargamos imagen y la forzamos a rellenar 1080x1920 (crop/resize)
            clip = ImageClip(path).set_duration(base_duration + transition_time)
            
            # Redimensionar al ancho de TikTok (1080) manteniendo aspecto y recortando lo que sobre
            clip = vfx.resize(clip, width=1080)
            if clip.h < 1920:
                clip = vfx.resize(clip, height=1920)
            
            # Centrar la imagen en un lienzo de 1080x1920
            clip = clip.on_color(size=(1080, 1920), color=(0,0,0), pos='center')

            # --- NUEVA LÓGICA DE ZOOM SIN BORDES ---
            zoom_factor = 0.15 # 15% de movimiento
            
            if i % 2 == 0:
                # ZOOM IN: Empieza en 1.1 y sube a 1.25
                clip = clip.resize(lambda t: 1.1 + (zoom_factor * t / (base_duration + transition_time)))
            else:
                # ZOOM OUT: Empieza en 1.25 y baja a 1.1
                clip = clip.resize(lambda t: (1.1 + zoom_factor) - (zoom_factor * t / (base_duration + transition_time)))
            
            # Transición suave
            if i > 0:
                clip = clip.crossfadein(transition_time)
            
            clips.append(clip)

        # 4. Concatenación final
        video = concatenate_videoclips(clips, method="compose", padding=-transition_time)
        video = video.set_duration(duration)
        video = video.set_audio(final_audio)

        # 5. Renderizado
        video.write_videofile(
            output_path, 
            fps=30, 
            codec="libx264", 
            audio_codec="aac",
            bitrate="5000k", # Calidad alta
            ffmpeg_params=["-vf", f"ass={subs_path}"]
        )

        return {"estado": "ok", "video": req.output_name}

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
