import streamlit as st
import pretty_midi
import io
import random
import os
import google.generativeai as genai
import time

# ページ設定（レイアウトをwideに変更して横並びに対応）
st.set_page_config(
    page_title="Piano Humanizer AI with Gemini",
    page_icon="🎹",
    layout="wide" 
)

st.title("🎹 Piano Humanizer AI v3.1")
st.caption("Powered by Google Gemini 2.0 Flash")

# --- ロジック1: 統計的ヒューマナイズ（既存） ---
def apply_statistical_humanize(note, vel_std, time_std):
    velocity_noise = random.gauss(0, vel_std * 20)
    pitch_bias = 3 if note.pitch > 72 else 0
    new_velocity = int(note.velocity + velocity_noise + pitch_bias)
    note.velocity = max(1, min(127, new_velocity))

    timing_noise = random.gauss(0, time_std * 0.05)
    new_start = max(0, note.start + timing_noise)
    new_end = max(new_start + 0.1, note.end + timing_noise)
    note.start = new_start
    note.end = new_end

# --- ロジック2: Gemini AI ヒューマナイズ（新規） ---
def apply_gemini_humanize(pm, api_key, progress_bar):
    """
    Gemini APIを使用して、MIDIデータから推奨されるベロシティ列を生成する
    """
    genai.configure(api_key=api_key)
    
    # 高速かつ最新の2.0 Flashモデルを使用
    model = genai.GenerativeModel('gemini-2.0-flash-exp')

    # ドラム以外のトラックを抽出
    target_instruments = [i for i in pm.instruments if not i.is_drum]
    
    if not target_instruments:
        return pm

    status_text = st.empty()
    
    # トラックごとに処理
    for inst_idx, instrument in enumerate(target_instruments):
        notes = instrument.notes
        
        chunk_size = 300 # 1回のAPIコールで処理するノート数
        chunks = [notes[i:i + chunk_size] for i in range(0, len(notes), chunk_size)]
        
        total_chunks = len(chunks)
        
        status_text.text(f"Track {inst_idx+1}: Geminiが演奏データを生成中... (全{len(notes)}音)")
        
        for i, chunk in enumerate(chunks):
            notes_str = ", ".join([f"({n.pitch},{n.end - n.start:.2f})" for n in chunk])
            
            prompt = f"""
            You are a professional pianist.
            Please determine the velocity (1-127) for each note in the following sequence to create a human-like, expressive performance.
            Consider phrasing and dynamics naturally.
            
            Input Format: (Pitch, Duration), (Pitch, Duration)...
            Input Data: [{notes_str}]
            
            Requirement:
            - Return ONLY a list of integer velocities separated by commas.
            - Do not include any other text or brackets.
            - The number of velocities MUST match the number of input notes exactly ({len(chunk)} notes).
            """
            
            try:
                # Geminiに生成させる
                response = model.generate_content(prompt)
                
                # テキストを数値リストに変換
                text_result = response.text.strip()
                text_result = text_result.replace('[', '').replace(']', '').replace('\n', ' ')
                velocities = [int(v.strip()) for v in text_result.split(',') if v.strip().isdigit()]
                
                # 適用
                for j, vel in enumerate(velocities):
                    if j < len(chunk):
                        chunk[j].velocity = max(1, min(127, vel))
                
                # 進捗バー更新
                current_progress = (inst_idx / len(target_instruments)) + ((i + 1) / total_chunks) * (1 / len(target_instruments))
                progress_bar.progress(min(current_progress, 1.0))
                
                # APIレート制限への配慮（少し待つ）
                time.sleep(1)

            except Exception as e:
                st.warning(f"Chunk {i+1} failed: {e}. Skipping AI processing for this part.")
                # エラー時は統計的処理でフォールバック
                for note in chunk:
                    apply_statistical_humanize(note, 0.3, 0.1)

    status_text.text("Geminiによる演奏生成が完了しました！")
    return pm

# --- メイン処理関数 ---
def process_midi(midi_file, mode, vel_std, time_std, api_key=None):
    try:
        pm = pretty_midi.PrettyMIDI(midi_file)
    except Exception as e:
        st.error(f"MIDI読み込みエラー: {e}")
        return None

    # プログレスバー
    progress_bar = st.progress(0)

    if mode == "Gemini":
        # Geminiモード
        if not api_key:
            st.error("APIキーが必要です。")
            return None
        pm = apply_gemini_humanize(pm, api_key, progress_bar)
        progress_bar.progress(1.0)
        
    else:
        # 統計モード
        total_notes = sum([len(i.notes) for i in pm.instruments])
        processed_notes = 0
        
        for instrument in pm.instruments:
            if instrument.is_drum: continue
            for note in instrument.notes:
                apply_statistical_humanize(note, vel_std, time_std)
                processed_notes += 1
                if total_notes > 0 and processed_notes % 100 == 0:
                    progress_bar.progress(processed_notes / total_notes)
        progress_bar.progress(1.0)

    return pm

# --- UI構築 ---

# カラムを作成（左：メイン操作、右：設定）
col_main, col_settings = st.columns([2, 1], gap="large")

with col_settings:
    st.header("🎛 設定")
    st.info("ここでAIの挙動を調整します")
    
    mode = st.radio(
        "処理モード",
        ("Statistical (統計/安定版)", "Gemini"),
        help="GeminiモードはAPIキーが必要です。曲の文脈を理解してベロシティを決定します。"
    )

    api_key = ""
    velocity_amount = 0.5
    timing_amount = 0.3

    if mode == "Gemini":
        st.markdown("### Google AI Studio API Key")
        api_key = st.text_input("APIキーを入力", type="password", help="Google AI Studioで取得したキーを入力してください")
        st.caption("[APIキーの取得はこちら](https://aistudio.google.com/app/apikey)")
    else:
        st.markdown("---")
        st.markdown("### 統計パラメータ")
        velocity_amount = st.slider("ベロシティ強度", 0.0, 1.0, 0.5)
        timing_amount = st.slider("タイミング揺れ", 0.0, 1.0, 0.3)

with col_main:
    st.subheader("📁 ファイル操作")
    uploaded_file = st.file_uploader("MIDIファイルをアップロード", type=["mid", "midi"])

    if uploaded_file is not None:
        # ファイル情報を表示
        st.success(f"読み込み完了: {uploaded_file.name}")
        
        st.markdown("---")
        st.markdown(f"**現在のモード:** {mode}")
        
        if st.button("変換を実行", type="primary", use_container_width=True):
            if mode == "Gemini" and not api_key:
                st.error("⚠️ Geminiモードを使用するには右側の設定パネルでAPIキーを入力してください。")
            else:
                with st.spinner("処理中..."):
                    # パラメータはモードによって使い分ける
                    v_param = velocity_amount if mode != "Gemini" else 0
                    t_param = timing_amount if mode != "Gemini" else 0
                    
                    processed_pm = process_midi(uploaded_file, mode, v_param, t_param, api_key)
                    
                    if processed_pm:
                        bio = io.BytesIO()
                        processed_pm.write(bio)
                        bio.seek(0)
                        
                        st.balloons()
                        st.success("完了しました！")
                        st.download_button(
                            label="🎹 Humanized MIDIをダウンロード",
                            data=bio,
                            file_name=f"gemini_humanized_{uploaded_file.name}" if api_key else f"humanized_{uploaded_file.name}",
                            mime="audio/midi",
                            use_container_width=True
                        )

st.markdown("---")
with st.expander("Gemini AIモードについて"):
    st.markdown("""
    **Gemini 2.0 Flash (Experimental)** モデルを使用して、あなたのMIDIデータを解析します。
    
    1. MIDIデータを楽譜（音の高さと長さのリスト）としてAIに送ります。
    2. AIは「プロのピアニスト」として振る舞い、文脈に応じた適切な強弱（ベロシティ）を考えます。
    3. AIが決めた強弱データを元のMIDIに適用します。
    """)