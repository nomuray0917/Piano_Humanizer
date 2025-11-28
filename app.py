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

st.title("🎹 Piano Humanizer AI v3.4 (エラー修正版)")
st.caption("Powered by Google Gemini 2.0 Flash")

# --- ロジック1: 統計的ヒューマナイズ ---
def apply_statistical_humanize(note, vel_std, time_std):
    # ベロシティにランダムなばらつきを追加
    velocity_noise = random.gauss(0, vel_std * 20)
    pitch_bias = 3 if note.pitch > 72 else 0
    new_velocity = int(note.velocity + velocity_noise + pitch_bias)
    note.velocity = max(1, min(127, new_velocity))

    # タイミングにランダムな揺らぎを追加
    timing_noise = random.gauss(0, time_std * 0.05)
    new_start = max(0, note.start + timing_noise)
    new_end = max(new_start + 0.1, note.end + timing_noise)
    note.start = new_start
    note.end = new_end

# --- ロジック2: Gemini AI ヒューマナイズ ---
def apply_gemini_humanize(pm, api_key, progress_bar, selected_instruments):
    """
    Gemini APIを使用して、選択されたインストゥルメントのMIDIデータから推奨されるベロシティ列を生成する
    """
    clean_key = api_key.strip()
    genai.configure(api_key=clean_key)
    
    model = genai.GenerativeModel('gemini-2.0-flash-exp')

    # 選択されたインストゥルメントのみを対象とする
    target_instruments = [inst for inst in pm.instruments if inst.name in selected_instruments]
    
    if not target_instruments:
        st.warning("処理対象のトラックが選択されていません。")
        return pm

    status_text = st.empty()
    
    total_instruments = len(target_instruments)
    
    for inst_idx, instrument in enumerate(target_instruments):
        notes = instrument.notes
        
        chunk_size = 300 # 1回のAPIコールで処理するノート数
        chunks = [notes[i:i + chunk_size] for i in range(0, len(notes), chunk_size)]
        total_chunks = len(chunks)
        
        status_text.text(f"Track {instrument.name}: Geminiが演奏データを生成中... ({len(notes)}音)")
        
        for i, chunk in enumerate(chunks):
            # (音高, 音長)のリストをプロンプト用に整形
            notes_str = ", ".join([f"({n.pitch},{n.end - n.start:.2f})" for n in chunk])
            
            prompt = f"""
            You are a professional musician playing the instrument: {instrument.name}.
            Please determine the velocity (1-127) for each note in the following sequence to create a human-like, expressive performance.
            Consider phrasing and dynamics naturally for this instrument.
            
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
                
                # 結果をパースして数値リストに変換
                text_result = response.text.strip()
                text_result = text_result.replace('[', '').replace(']', '').replace('\n', ' ')
                velocities = [int(v.strip()) for v in text_result.split(',') if v.strip().isdigit()]
                
                # 適用
                for j, vel in enumerate(velocities):
                    if j < len(chunk):
                        chunk[j].velocity = max(1, min(127, vel))
                
                # 進捗バー更新
                current_progress = (inst_idx / total_instruments) + ((i + 1) / total_chunks) * (1 / total_instruments)
                progress_bar.progress(min(current_progress, 1.0))
                
                time.sleep(1) # APIレート制限への配慮

            except Exception as e:
                st.warning(f"Track {instrument.name}, Chunk {i+1} failed: {e}. Skipping AI processing for this part.")
                # エラー時は統計的処理でフォールバック
                for note in chunk:
                    apply_statistical_humanize(note, 0.3, 0.1)

    status_text.text("Geminiによる演奏生成が完了しました！")
    return pm

# --- メイン処理関数 ---
def process_midi(midi_file_data, mode, vel_std, time_std, api_key, selected_instruments):
    try:
        # バイナリデータからPrettyMIDIオブジェクトを再構築
        pm = pretty_midi.PrettyMIDI(io.BytesIO(midi_file_data))
    except Exception as e:
        st.error(f"MIDI読み込みエラー: {e}")
        return None

    # プログレスバー
    progress_bar = st.progress(0)

    if mode == "Gemini":
        if not api_key:
            st.error("APIキーが必要です。")
            return None
        pm = apply_gemini_humanize(pm, api_key.strip(), progress_bar, selected_instruments)
        
    else:
        # 統計モード：選択されたトラックのみを処理
        target_instruments = [inst for inst in pm.instruments if inst.name in selected_instruments]
        
        total_notes = sum([len(i.notes) for i in target_instruments])
        processed_notes = 0
        
        for instrument in target_instruments:
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

# アップロードされたMIDIデータをセッション状態に保存する
if 'midi_data' not in st.session_state:
    st.session_state['midi_data'] = None

# --- 設定パネル (右側) ---
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

# --- メイン操作パネル (左側) ---
with col_main:
    st.subheader("📁 ファイル操作")
    uploaded_file = st.file_uploader("MIDIファイルをアップロード", type=["mid", "midi"])

    if uploaded_file is not None:
        # ファイルが新しくアップロードされたらセッション状態を更新
        if st.session_state['midi_data'] is None or st.session_state['midi_data']['name'] != uploaded_file.name:
            try:
                # 処理用にPrettyMIDIオブジェクトを作成
                pm = pretty_midi.PrettyMIDI(uploaded_file)
                # インストゥルメント情報とファイルデータ本体を保存
                instrument_names = [i.name if i.name else f"Track {idx+1} ({pretty_midi.instrument_name_to_program(i.program)})" for idx, i in enumerate(pm.instruments)]
                uploaded_file.seek(0) # ファイルポインタを先頭に戻す
                midi_bytes = uploaded_file.read() # ファイルのバイナリデータを読み取る

                # セッションステートにバイナリデータと名前、トラック情報を保存
                st.session_state['midi_data'] = {
                    'bytes': midi_bytes, 
                    'name': uploaded_file.name, 
                    'instruments': instrument_names
                }
                st.success(f"読み込み完了: {uploaded_file.name}")
            except Exception as e:
                st.error(f"MIDI解析エラー: {e}")
                st.session_state['midi_data'] = None
                uploaded_file = None

        if st.session_state['midi_data']:
            st.markdown("---")
            
            # --- トラック選択機能 ---
            all_instruments = st.session_state['midi_data']['instruments']
            
            st.subheader("🎵 処理対象トラックの選択")
            selected_instruments = st.multiselect(
                "AI/統計処理を適用したいトラックを選んでください（複数選択可）",
                options=all_instruments,
                default=[name for name in all_instruments if "Piano" in name or "Keyboard" in name or "Lead" in name]
            )
            
            st.markdown(f"**現在のモード:** {mode}")
            
            if st.button("変換を実行", type="primary", use_container_width=True, disabled=not selected_instruments):
                if not selected_instruments:
                    st.error("⚠️ 処理対象トラックを1つ以上選択してください。")
                elif mode == "Gemini" and not api_key:
                    st.error("⚠️ Geminiモードを使用するには右側の設定パネルでAPIキーを入力してください。")
                else:
                    with st.spinner("処理中..."):
                        # セッションステートからバイナリデータを取得
                        midi_file_data = st.session_state['midi_data']['bytes']
                        
                        v_param = velocity_amount if mode != "Gemini" else 0
                        t_param = timing_amount if mode != "Gemini" else 0
                        
                        # バイナリデータ（midi_file_data）を渡すように変更
                        processed_pm = process_midi(
                            midi_file_data, 
                            mode, 
                            v_param, 
                            t_param, 
                            api_key, 
                            selected_instruments
                        )
                        
                        if processed_pm:
                            # 処理後のMIDIをバイナリデータとして書き出す
                            bio = io.BytesIO()
                            processed_pm.write(bio)
                            bio.seek(0)
                            
                            st.balloons()
                            st.success("完了しました！")
                            st.download_button(
                                label="🎹 Humanized MIDIをダウンロード",
                                data=bio,
                                file_name=f"humanized_{st.session_state['midi_data']['name']}",
                                mime="audio/midi",
                                use_container_width=True
                            )

# --- FAQセクション ---
st.markdown("---")
st.subheader("❓ よくある質問 (FAQ)")

with st.expander("Q. Google Gemini APIキーはどこで取得できますか？無料ですか？"):
    st.markdown("""
    **A. 無料で取得可能です。**
    
    1. [Google AI Studio](https://aistudio.google.com/app/apikey) にアクセスします。
    2. Googleアカウントでログインします。
    3. **「Create API key」** ボタンを押します。
    4. 生成されたキー（`AIza`で始まる文字列）をコピーして、このアプリの右側の設定欄に入力してください。
    
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
    - **おすすめ:** ポップスのバッキング、BGM、ドラム以外の全般。処理が非常に高速です。
    - **特徴:** 数学的な計算で「人間らしいズレ」を作ります。

    **🤖 Gemini**
    - **おすすめ:** ピアノソロ、バラードのメロディ、感情的な表現が欲しい時。
    - **特徴:** AIが楽譜を読んで「ここは強く弾こう」と判断し、より表現豊かな演奏を生成します。
    """)

with st.expander("Q. エラーが出たり、処理が止まってしまいます。"):
    st.markdown("""
    **A. 以下の点を確認してください。**
    
    - **曲が長すぎる:** Geminiモードは数分かかることがあります。まずは短い曲で試してみてください。
    - **APIキーの間違い:** コピー時に余分なスペースが入っていないか確認してください。
    - **MIDIファイルの問題:** 特殊なデータが含まれていると失敗することがあります。「統計モード」なら動く場合が多いです。
    """)