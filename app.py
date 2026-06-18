import os
import wave
import re
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

def parse_transcript(filename="input.txt"):
    if not os.path.exists(filename):
        raise FileNotFoundError(f"❌ Error: '{filename}' not found.")
    with open(filename, "r", encoding="utf-8") as f:
        content = f.read()

    style_match = re.search(r"Style:\s*(.*)", content)
    context_match = re.search(r"Sample Context:\s*([\s\S]*?)(?=##|\Z)", content)
    
    style_context = ""
    if style_match: style_context += f"Style: {style_match.group(1).strip()}. "
    if context_match: style_context += f"Context: {context_match.group(1).strip()}"

    speaker_lines = re.findall(r"(Speaker \d+):\s*(.*)", content)
    return style_context, speaker_lines

def generate_silence(duration_seconds=1.2, rate=24000, sample_width=2):
    return b'\x00' * int(rate * sample_width * duration_seconds)

def main():
    try:
        style_context, dialogue = parse_transcript("input.txt")
        if not dialogue:
            print("❌ No dialogue found.")
            return

        client = genai.Client()
        final_audio_stream = bytearray()
        
        for idx, (speaker, text) in enumerate(dialogue):
            print(f"🎙️ Generating: Line {idx + 1} ({speaker})...")
            
            # ปรับสไตล์บรีฟให้ชัดเจนขึ้นสำหรับความเป็นผู้ประกาศข่าว
            newscaster_style = (
                "Style: Professional newscaster, authoritative, formal broadcast cadence, "
                "clear Thai articulation, steady pacing, objective tone."
            )
            
            voice_name = "Aoede" if speaker == "Speaker 1" else "Puck"
            
            # นำบรีฟผู้ประกาศข่าวและบทพูดมารวมกัน
            full_prompt = f"[{newscaster_style}]. Read the following text as a formal news broadcast: {text}"

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

            audio_bytes = response.candidates[0].content.parts[0].inline_data.data
            final_audio_stream.extend(audio_bytes)
            
            if idx < len(dialogue) - 1:
                final_audio_stream.extend(generate_silence())

        if final_audio_stream:
            with wave.open("output.wav", "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(bytes(final_audio_stream))
            print("🎉 Success! Saved to output.wav")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()