import os
import wave
import re
import io
import hashlib
import argparse
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

def parse_transcript(filename="input.txt"):
    """
    Parses style context and speaker dialogue from the transcript file.
    Supports multi-line speaker paragraphs.
    """
    if not os.path.exists(filename):
        raise FileNotFoundError(f"❌ Error: '{filename}' not found.")
    with open(filename, "r", encoding="utf-8") as f:
        content = f.read()

    style_match = re.search(r"Style:\s*(.*)", content)
    context_match = re.search(r"Sample Context:\s*([\s\S]*?)(?=##|\Z)", content)
    
    style_context = ""
    if style_match:
        style_context += f"Style: {style_match.group(1).strip()}. "
    if context_match:
        style_context += f"Context: {context_match.group(1).strip()}"

    speaker_lines = []
    current_speaker = None
    current_text = []

    lines = content.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Match Speaker lines like "Speaker 1:"
        match = re.match(r"^(Speaker \d+):\s*(.*)", line)
        if match:
            if current_speaker:
                speaker_lines.append((current_speaker, " ".join(current_text)))
            current_speaker = match.group(1)
            current_text = [match.group(2).strip()]
        else:
            # Multi-line text continuation (skip headers/metadata)
            if (current_speaker and 
                not line.startswith("#") and 
                not line.startswith("Style:") and 
                not line.startswith("Sample Context:")):
                current_text.append(line)
                
    if current_speaker:
        speaker_lines.append((current_speaker, " ".join(current_text)))
        
    return style_context, speaker_lines

def translate_emotional_cues(text: str) -> str:
    """
    Translates common Thai emotional/conversational expressions in the dialogue
    into standard English TTS tag cues (e.g. [laughs], [sighs]).
    """
    processed = text
    
    # 1. Bracketed or parenthesized cues
    cues_map = {
        "หัวเราะ": "laughs",
        "ถอนหายใจ": "sighs",
        "หืม": "puzzled",
        "อ้าว": "surprised",
        "อึ้ก": "gasp",
        "โห": "wowed",
        "ยิ้ม": "smiling"
    }
    for th, en in cues_map.items():
        processed = re.sub(rf"[(\[][\s]*{th}[\s]*[)\]]", f"[{en}]", processed)
        
    # 2. Spoken leading/trailing emotional expressions
    processed = re.sub(r"(^|[\s,.:;?])อึ้ก([.\s]*)", r"\1[gasp]\2", processed)
    processed = re.sub(r"(^|[\s,.:;?])โห([.\s]*)", r"\1[wowed]\2", processed)
    processed = re.sub(r"(^|[\s,.:;?])อ้าว([.\s]*)", r"\1[surprised] \2", processed)
    processed = re.sub(r"(^|[\s,.:;?])หืม(\?|[.\s]*)", r"\1[puzzled] หืม\2", processed)
    
    return processed

def generate_silence(duration_seconds=0.6, rate=24000, sample_width=2, channels=1):
    """
    Generates a byte string of silent PCM audio.
    """
    return b'\x00' * int(rate * sample_width * channels * duration_seconds)

def main():
    parser = argparse.ArgumentParser(description="🎙️ Thai 2-Person Podcast Audio Generator")
    parser.add_argument("--input", "-i", default="input.txt", help="Path to input transcript file (default: input.txt)")
    parser.add_argument("--output", "-o", default="output.wav", help="Path to output WAV file (default: output.wav)")
    parser.add_argument("--no-cache", action="store_true", help="Disable cache and force regeneration")
    parser.add_argument("--clear-cache", action="store_true", help="Clear the cache directory and exit")
    parser.add_argument("--file-style", action="store_true", help="Use style from input.txt instead of conversational style")
    args = parser.parse_args()

    # Clear cache action
    if args.clear_cache:
        import shutil
        if os.path.exists(".cache"):
            shutil.rmtree(".cache")
            print("🧹 Cache cleared successfully.")
        else:
            print("🧹 Cache is already empty.")
        return

    try:
        style_context, dialogue = parse_transcript(args.input)
        if not dialogue:
            print("❌ No dialogue found.")
            return

        print(f"📖 Loaded '{args.input}' with {len(dialogue)} dialogue turns.")
        
        client = genai.Client()
        dialogue_segments = []
        
        # Define speaker personas/voices for conversational podcast
        speaker_configs = {
            "Speaker 1": {
                "voice": "Kore",
                "style": "Style: Casual podcast conversation, warm, energetic, friendly young female co-host, natural Thai speech, natural conversational pacing, clear articulation, realistic pauses."
            },
            "Speaker 2": {
                "voice": "Charon",
                "style": "Style: Casual podcast conversation, wise, warm, mature male co-host (uncle figure), natural Thai speech, natural conversational pacing, clear articulation, realistic pauses."
            }
        }

        # Print style info
        if args.file_style:
            print("ℹ️ Using overall style context from transcript file.")
        else:
            print("ℹ️ Using optimized conversational podcast styles (Fah -> Kore, Uncle Quin -> Charon).")

        for idx, (speaker, text) in enumerate(dialogue):
            # 1. Translate emotional expressions
            clean_text = translate_emotional_cues(text)
            
            # 2. Get speaker config
            config = speaker_configs.get(speaker, {
                "voice": "Kore" if "1" in speaker else "Charon",
                "style": speaker_configs["Speaker 1"]["style"] if "1" in speaker else speaker_configs["Speaker 2"]["style"]
            })
            
            voice_name = config["voice"]
            style_brief = style_context if (args.file_style and style_context) else config["style"]
            
            # Combine brief and text
            full_prompt = f"[{style_brief}]. Read the following text naturally: {clean_text}"

            print(f"🎙️ [{idx + 1}/{len(dialogue)}] Speaker: {speaker} | Voice: {voice_name}")
            print(f"   Original: {text[:60]}...")
            if text != clean_text:
                print(f"   Enhanced: {clean_text[:60]}...")

            # 3. Check / fetch cache (cache key depends on voice, style, and cleaned text)
            cache_payload = f"{voice_name}:{style_brief}:{clean_text}".encode("utf-8")
            cache_hash = hashlib.sha256(cache_payload).hexdigest()
            cache_file = os.path.join(".cache", f"{cache_hash}.raw")

            pcm_bytes = None
            if not args.no_cache and os.path.exists(cache_file):
                print("   ⚡ [Cache Hit]")
                with open(cache_file, "rb") as f:
                    pcm_bytes = f.read()
            else:
                print("   🌐 [Cache Miss] Generating audio via Gemini API...")
                response = client.models.generate_content(
                    model="gemini-3.1-flash-tts-preview",
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                            )
                        ),
                    )
                )

                if not response.candidates or not response.candidates[0].content.parts:
                    raise ValueError(f"Failed to generate audio for line {idx + 1}")

                part = response.candidates[0].content.parts[0]
                pcm_bytes = part.inline_data.data

                # Save to cache
                if not args.no_cache:
                    os.makedirs(".cache", exist_ok=True)
                    with open(cache_file, "wb") as f:
                        f.write(pcm_bytes)

            dialogue_segments.append(pcm_bytes)

        if not dialogue_segments:
            print("❌ No audio segments were successfully generated.")
            return

        # Fixed parameters for Gemini TTS audio (audio/l16; rate=24000; channels=1)
        sample_rate = 24000
        sample_width = 2  # 16-bit linear PCM is 2 bytes per sample
        channels = 1      # Mono

        print(f"\n🎧 Stitching audio segments (Rate: {sample_rate}Hz, Channels: {channels})...")
        
        final_pcm_stream = bytearray()
        for idx, pcm_data in enumerate(dialogue_segments):
            final_pcm_stream.extend(pcm_data)
            
            # Insert conversational silence between speakers (0.6 seconds)
            if idx < len(dialogue_segments) - 1:
                silence = generate_silence(
                    duration_seconds=0.6,
                    rate=sample_rate,
                    sample_width=sample_width,
                    channels=channels
                )
                final_pcm_stream.extend(silence)

        # Write final WAV file
        with wave.open(args.output, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            wf.writeframes(bytes(final_pcm_stream))

        print(f"🎉 Success! Podcast output saved to '{args.output}'")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()