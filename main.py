import os
import re
import numpy as np
from PIL import Image
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from moviepy.editor import concatenate_videoclips, AudioFileClip, CompositeAudioClip, VideoClip

app = FastAPI()
MEDIA_FOLDER = "/media"

class VideoRequest(BaseModel):
    prefix: str
    output_name: str
    audio_bg: str = "taudio-1.mp3"

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', s)]

# --- MOTOR DE ZOOM SUAVE (CERO TEMBLORES) ---
def create_smooth_zoom_clip(img_path, duration, zoom_in=True, target_w=1080, target_h=1920):
    # Abrimos la imagen original con la máxima calidad
    img = Image.open(img_path).convert('RGB')
    img_w, img_h = img.size

    # Calculamos cómo encajarla en 9:16 sin distorsionar
    target_ratio = target_w / target_h
    img_ratio = img_w / img_h

    if img_ratio > target_ratio:
        new_w = img_h * target_ratio
        new_h = img_h
    else:
        new_w = img_w
        new_h = img_w / target_ratio

    # Coordenadas de la ventana base (centrada)
    left = (img_w - new_w) / 2
    top = (img_h - new_h) / 2

    zoom_factor = 0.15 # Nivel de zoom (15%)
    
    # Esta función se ejecuta para cada fotograma del video
    def make_frame(t):
        progress = t / duration
        
        if zoom_in:
            # Zoom In: La ventana se hace más pequeña (nos acercamos)
            current_zoom = 1.0 - (zoom_factor * progress)
        else:
            # Zoom Out: La ventana se hace más grande (nos alejamos)
            current_zoom = (1.0 - zoom_factor) + (zoom_factor * progress)
        
        # Tamaño actual de la ventana
        current_w = new_w * current_zoom
        current_h = new_h * current_zoom
        
        # Mantener la ventana siempre centrada
        center_x = left + new_w / 2
        center_y = top + new_h / 2
        
        c_left = center_x - current_w / 2
        c_top = center_y - current_h / 2
        c_right = center_x + current_w / 2
        c_bottom = center_y + current_h / 2
        
        # Recortamos la ventana y la forzamos a 1080x1920 con calidad LANCZOS (súper suave)
        cropped = img.crop((c_left, c_top, c_right, c_bottom))
        resized = cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)
        
        # Convertimos la imagen perfecta en un fotograma de video
        return np.array(resized)

    # Devolvemos un clip de video generado matemáticamente
    return VideoClip(make_frame, duration=duration)


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

        # 3. Procesar Imágenes con nuestro nuevo Motor Suave
        img_files = [f for f in os.listdir(MEDIA_FOLDER) 
                     if f.startswith(f"{req.prefix}_") and f.endswith(('.png', '.jpg', '.jpeg'))]
        img_files.sort(key=natural_sort_key)

        num_images = len(img_files)
        base_duration = duration / num_images
        transition_time = 0.5 

        clips = []
        for i, filename in enumerate(img_files):
            path = os.path.join(MEDIA_FOLDER, filename)
            clip_duration = base_duration + transition_time
            
            # Pares hacen Zoom In (True), Impares hacen Zoom Out (False)
            zoom_in = (i % 2 == 0)
            
            # Usamos la función mágica
            clip = create_smooth_zoom_clip(path, clip_duration, zoom_in=zoom_in)
            
            # Transición
            if i > 0:
                clip = clip.crossfadein(transition_time)
            
            clips.append(clip)

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
