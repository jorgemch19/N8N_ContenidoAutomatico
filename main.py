import os
import re
import numpy as np
from PIL import Image, ImageEnhance
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from moviepy.editor import concatenate_videoclips, AudioFileClip, CompositeAudioClip, VideoClip, CompositeVideoClip, ColorClip, ImageClip

app = FastAPI()
MEDIA_FOLDER = "/media"

class VideoRequest(BaseModel):
    prefix: str
    output_name: str
    audio_bg: str = "taudio-1.mp3"

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', s)]

# --- CREADOR DE VIÑETEADO OSCURO (VIGNETTE) ---
def create_vignette_clip(width=1080, height=1920, duration=10):
    # Crear un degradado circular matemático
    x = np.linspace(-1, 1, width)
    y = np.linspace(-1, 1, height)
    X, Y = np.meshgrid(x, y)
    R = np.sqrt(X**2 + Y**2)
    
    # 0 en el centro (transparente), sube hasta 0.6 (60% oscuro) en los bordes
    mask = np.clip((R - 0.5) / 0.7, 0, 0.6)
    
    # Imagen negra con la máscara aplicada
    black = np.zeros((height, width, 3), dtype=np.uint8)
    vignette = ImageClip(black).set_duration(duration)
    mask_clip = ImageClip(mask, ismask=True).set_duration(duration)
    
    return vignette.set_mask(mask_clip)

# --- MOTOR DE ZOOM SUAVE + COLOR POP ---
def create_smooth_zoom_clip(img_path, duration, zoom_in=True, target_w=1080, target_h=1920):
    # 1. Abrimos la imagen original
    img = Image.open(img_path).convert('RGB')
    
    # --- EFECTO 3: COLOR POP (Saturación y Contraste) ---
    img = ImageEnhance.Color(img).enhance(1.3)     # +30% de color
    img = ImageEnhance.Contrast(img).enhance(1.15) # +15% de contraste

    img_w, img_h = img.size
    target_ratio = target_w / target_h
    img_ratio = img_w / img_h

    if img_ratio > target_ratio:
        new_w = img_h * target_ratio
        new_h = img_h
    else:
        new_w = img_w
        new_h = img_w / target_ratio

    left = (img_w - new_w) / 2
    top = (img_h - new_h) / 2
    zoom_factor = 0.15 
    
    def make_frame(t):
        progress = t / duration
        if zoom_in:
            current_zoom = 1.0 - (zoom_factor * progress)
        else:
            current_zoom = (1.0 - zoom_factor) + (zoom_factor * progress)
        
        current_w = new_w * current_zoom
        current_h = new_h * current_zoom
        center_x = left + new_w / 2
        center_y = top + new_h / 2
        
        c_left = center_x - current_w / 2
        c_top = center_y - current_h / 2
        c_right = center_x + current_w / 2
        c_bottom = center_y + current_h / 2
        
        cropped = img.crop((c_left, c_top, c_right, c_bottom))
        resized = cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)
        return np.array(resized)

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
            clip_duration = base_duration + transition_time
            zoom_in = (i % 2 == 0)
            
            clip = create_smooth_zoom_clip(path, clip_duration, zoom_in=zoom_in)
            
            if i > 0:
                clip = clip.crossfadein(transition_time)
            clips.append(clip)

        # 4. Unir clips base
        base_video = concatenate_videoclips(clips, method="compose", padding=-transition_time)
        base_video = base_video.set_duration(duration)

        # --- EFECTO 4: VIÑETEADO ---
        vignette_layer = create_vignette_clip(width=1080, height=1920, duration=duration)

        # --- EFECTO 5: FLASH BLANCO INICIAL (CORREGIDO) ---
        flash_duration = 0.5
        # Creamos un cuadro blanco y le decimos que se desvanezca (crossfadeout) en 0.5 segundos
        white_flash = ColorClip(size=(1080, 1920), color=(255, 255, 255)).set_duration(flash_duration)
        white_flash = white_flash.crossfadeout(flash_duration)

        # Juntar capas: Fondo(imágenes) + Sombra(viñeteado) + Destello
        final_video = CompositeVideoClip([base_video, vignette_layer, white_flash])
        
        # Sincronizar audio
        final_video = final_video.set_audio(final_audio)

        # 5. Renderizado
        final_video.write_videofile(
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
