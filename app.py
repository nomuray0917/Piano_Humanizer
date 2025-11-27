import streamlit as st
import pretty_midi
import io
import random
import os
import google.generativeai as genai
import time

# ページ設定
st.set_page_config(
    page_title="Piano Humanizer AI with Gemini",
    page_icon="🎹",
    layout="wide" 
)

st.title("🎹 Piano Humanizer AI")
st.caption("Powered by Google Gemini 2.0 Flash")

# --- ロジック1: 統計的ヒューマナイズ ---
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

# --- ロジック2: Gemini AI ヒューマナイズ ---
def apply_gemini_humanize(pm, api_key, progress_bar):
    clean_key = api_key.strip()
    genai.configure(api_key=clean_key)
    
    model = genai.GenerativeModel('gemini-2.0-flash-exp')

    target_instruments = [i for i in pm.instruments if not i.is_drum]
    
    if not target_instruments:
        return pm

    status_text = st.empty()
    
    for inst_idx, instrument in enumerate(target_instruments):
        notes = instrument.notes
        chunk_size = 300 
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
                response = model.generate_content(prompt)
                text_result = response.text.strip()
                text_result = text_result.replace('[', '').replace(']', '').replace('\n', ' ')
                velocities = [int(v.strip()) for v in text_result.split(',') if v.strip().isdigit()]
                
                for j, vel in enumerate(velocities):
                    if j < len(chunk):
                        chunk[j].velocity = max(1, min(127, vel))
                
                current_progress = (inst_idx / len(target_instruments)) + ((i + 1) / total_chunks) * (1 / len(target_instruments))
                progress_bar.progress(min(current_progress, 1.0))
                time.sleep(1)

            except Exception as e:
                st.warning(f"Chunk {i+1} failed: {e}. Skipping AI processing for this part.")
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

    progress_bar = st.progress(0)

    if mode == "Gemini":
        if not api_key:
            st.error("APIキーが必要です。")
            return None
        pm = apply_gemini_humanize(pm, api_key.strip(), progress_bar)
        progress_bar.progress(1.0)
        
    else:
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

col_main, col_settings = st.columns([2, 1], gap="large")

with col_settings:
    st.header("🎛 設定")
    st.info("ここでAIの挙動を調整します")
    
    mode = st.radio(
        "処理モード",
        ("Statistical (統計/安定版)", "Gemini"),
        help="GeminiモードはAPIキーが必要です。"
    )

    api_key = ""
    velocity_amount = 0.5
    timing_amount = 0.3

    if mode == "Gemini":
        st.markdown("### Google AI Studio API Key")
        api_key_input = st.text_input("APIキーを入力", type="password", help="Google AI Studioで取得したキーを入力してください")
        api_key = api_key_input.strip() if api_key_input else ""
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
        st.success(f"読み込み完了: {uploaded_file.name}")
        st.markdown("---")
        
        if st.button("変換を実行", type="primary", use_container_width=True):
            if mode == "Gemini" and not api_key:
                st.error("⚠️ Geminiモードを使用するには右側の設定パネルでAPIキーを入力してください。")
            else:
                with st.spinner("処理中..."):
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

# --- FAQセクション (新機能) ---
st.markdown("---")
st.subheader("❓ よくある質問 (FAQ)")

with st.expander("Q. Google Gemini APIキーはどこで取得できますか？無料ですか？"):
    st.markdown("""
    **A. 無料で取得可能です。**
    
    1. [Google AI Studio](https://aistudio.google.com/app/apikey) にアクセスします。
    2. Googleアカウントでログインします。
    3. **「Create API key」** ボタンを押します。
    4. 生成されたキー（`AIza`で始まる文字列）をコピーして、このアプリの右側（スマホなら下）の設定欄に入力してください。
    
    ※ 現在のGoogleのプランでは、個人利用の範囲内であれば無料で十分な回数を利用できます。
    """)

with st.expander("Q. APIキーを入力しても安全ですか？保存されませんか？"):
    st.markdown("""
    **A. はい、安全です。**
    
    入力されたAPIキーは、あなたのブラウザからGoogleのサーバーへ通信するためだけに使用されます。
    **このアプリの開発者やサーバーがあなたのキーを保存・記録することは一切ありません。**
    ページを閉じたりリロードすると、キー情報はきれいに消去されます。
    """)

with st.expander("Q. 「統計モード」と「Geminiモード」どちらを使えばいいですか？"):
    st.markdown("""
    **🎹 Statistical (統計/安定版)**
    - **おすすめ:** ポップスのバッキング、BGM、ドラム以外の全般。
    - **特徴:** 数学的な計算で「人間らしいズレ」を作ります。処理が一瞬で終わります。
    
    **🤖 Gemini**
    - **おすすめ:** ピアノソロ、バラードのメロディ、感情的な表現が欲しい時。
    - **特徴:** AIが楽譜を読んで「ここは強く弾こう」と判断します。処理に時間がかかりますが、ドラマチックな演奏になります。
    """)

with st.expander("Q. エラーが出たり、処理が止まってしまいます。"):
    st.markdown("""
    **A. 以下の点を確認してください。**
    
    - **曲が長すぎる:** Geminiモードは数分かかることがあります。まずは短い曲で試してみてください。
    - **APIキーの間違い:** コピー時に余分なスペースが入っていないか確認してください。
    - **MIDIファイルの問題:** 特殊なデータが含まれていると失敗することがあります。「統計モード」なら動く場合が多いです。
    """)