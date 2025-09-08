import streamlit as st
import requests
import pandas as pd
import time
import datetime
import plotly.express as px
import pytz

# Set page configuration
st.set_page_config(
    page_title="SHOWROOM Event Dashboard",
    page_icon="🎤",
    layout="wide",
)

# -----------------------
# ヘルパー関数
# -----------------------
HEADERS = {"User-Agent": "Mozilla/5.0"}
JST = pytz.timezone('Asia/Tokyo')

@st.cache_data(ttl=3600)
def get_events():
    """Fetches a list of ongoing SHOWROOM events."""
    events = []
    page = 1
    for _ in range(10):
        url = f"https://www.showroom-live.com/api/event/search?page={page}&include_ended=0"
        try:
            response = requests.get(url, headers=HEADERS, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            page_events = []
            if isinstance(data, dict):
                if 'events' in data:
                    page_events = data['events']
                elif 'event_list' in data:
                    page_events = data['event_list']
            elif isinstance(data, list):
                page_events = data
            
            if not page_events:
                break
            
            events.extend(page_events)
            page += 1
        except requests.exceptions.RequestException as e:
            st.error(f"イベントデータ取得中にエラーが発生しました: {e}")
            return []
        except ValueError:
            st.error(f"APIからのJSONデコードに失敗しました: {response.text}")
            return []
            
    return events

# ランキングAPIの候補を定義
RANKING_API_CANDIDATES = [
    "https://www.showroom-live.com/api/event/{event_url_key}/ranking?page={page}",
    "https://www.showroom-live.com/api/event/ranking?event_id={event_id}&page={page}",
]

@st.cache_data(ttl=300)
def get_event_ranking_with_room_id(event_url_key, event_id, max_pages=10):
    """
    Fetches ranking data, including room_id, by trying multiple API endpoints.
    Returns a dictionary of {room_name: {room_id, rank, point, ...}}
    """
    all_ranking_data = []
    
    for base_url in RANKING_API_CANDIDATES:
        try:
            temp_ranking_data = []
            for page in range(1, max_pages + 1):
                url = base_url.format(event_url_key=event_url_key, event_id=event_id, page=page)
                response = requests.get(url, headers=HEADERS, timeout=10)

                if response.status_code == 404:
                    break
                
                response.raise_for_status()
                data = response.json()
                
                ranking_list = None
                if isinstance(data, dict) and 'ranking' in data:
                    ranking_list = data['ranking']
                elif isinstance(data, dict) and 'event_list' in data:
                    ranking_list = data['event_list']
                elif isinstance(data, list):
                    ranking_list = data
                
                if not ranking_list:
                    break
                
                temp_ranking_data.extend(ranking_list)
            
            if temp_ranking_data and any('room_id' in r for r in temp_ranking_data):
                all_ranking_data = temp_ranking_data
                break
            
        except requests.exceptions.RequestException:
            continue

    if not all_ranking_data:
        return None

    room_map = {}
    for room_info in all_ranking_data:
        room_id = room_info.get('room_id')
        room_name = room_info.get('room_name') or room_info.get('user_name')
        
        if room_id and room_name:
            room_map[room_name] = {
                'room_id': room_id,
                'rank': room_info.get('rank'),
                'point': room_info.get('point')
            }
            
    return room_map

def get_room_event_info(room_id):
    """Fetches event and support info for a specific room."""
    url = f"https://www.showroom-live.com/api/room/event_and_support?room_id={room_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        return data
            
    except requests.exceptions.RequestException as e:
        st.error(f"ルームID {room_id} のデータ取得中にエラーが発生しました: {e}")
        return None

@st.cache_data(ttl=30)  # キャッシュ有効期間を短く設定
def get_onlives_rooms():
    """Fetches a list of currently live room IDs."""
    onlives = set()
    try:
        url = "https://www.showroom-live.com/api/live/onlives"
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            for live_type in ['official_lives', 'talent_lives', 'amateur_lives']:
                if live_type in data and isinstance(data[live_type], list):
                    for room in data[live_type]:
                        # APIレスポンスのルームIDを安全に抽出
                        room_id = None
                        if 'room_id' in room:
                            room_id = room['room_id']
                        elif 'live_info' in room and 'room_id' in room['live_info']:
                            room_id = room['live_info']['room_id']
                        elif 'room' in room and 'room_id' in room['room']:
                            room_id = room['room']['room_id']
                        
                        if room_id:
                            onlives.add(int(room_id)) # int型に変換して追加

    except requests.exceptions.RequestException as e:
        st.warning(f"ライブ配信情報取得中にエラーが発生しました: {e}")
    except ValueError:
        st.warning("ライブ配信情報のJSONデコードに失敗しました。")
    return onlives


# --- Main Application Logic ---

def main():
    st.title("🎤 SHOWROOMイベント可視化ツール")
    st.write("ライバーとリスナーのための、イベント順位とポイント差をリアルタイムで可視化するツールです。")
    
    # セッションステートの初期化
    if "room_map_data" not in st.session_state:
        st.session_state.room_map_data = None
    if "selected_event_name" not in st.session_state:
        st.session_state.selected_event_name = None
    if "selected_room_names" not in st.session_state:
        st.session_state.selected_room_names = []
    
    # --- Event Selection Section ---
    st.header("1. イベントを選択")
    
    events = get_events()
    if not events:
        st.warning("現在開催中のイベントが見つかりませんでした。")
        return

    event_options = {event['event_name']: event for event in events}
    selected_event_name = st.selectbox(
        "イベント名を選択してください:", 
        options=list(event_options.keys()),
        key="event_selector"
    )
    
    if not selected_event_name:
        st.warning("イベントを選択してください。")
        return

    selected_event_data = event_options.get(selected_event_name)

    # イベント期間とURLリンク
    event_url = f"https://www.showroom-live.com/event/{selected_event_data.get('event_url_key')}"
    started_at_dt = datetime.datetime.fromtimestamp(selected_event_data.get('started_at'), JST)
    ended_at_dt = datetime.datetime.fromtimestamp(selected_event_data.get('ended_at'), JST)
    event_period_str = f"{started_at_dt.strftime('%Y/%m/%d %H:%M')} - {ended_at_dt.strftime('%Y/%m/%d %H:%M')}"
    
    st.info(f"選択されたイベント: **{selected_event_name}**")
    st.markdown(f"**▶ [イベントページへ移動する]({event_url})**", unsafe_allow_html=True)

    # セッションステートのリセット
    if st.session_state.selected_event_name != selected_event_name:
        st.session_state.selected_event_name = selected_event_name
        st.session_state.room_map_data = None
        st.session_state.selected_room_names = []
        st.rerun()

    if not selected_event_data:
        st.error(f"選択されたイベント '{selected_event_name}' の詳細情報が見つかりませんでした。別のイベントを選択してください。")
        return

    selected_event_key = selected_event_data.get('event_url_key', '')
    selected_event_id = selected_event_data.get('event_id')
    
    # --- Room Selection Section ---
    st.header("2. 比較したいルームを選択")
    
    if st.session_state.room_map_data is None:
        with st.spinner('イベント参加者情報を取得中...'):
            st.session_state.room_map_data = get_event_ranking_with_room_id(selected_event_key, selected_event_id)

    if not st.session_state.room_map_data:
        st.warning("このイベントの参加者情報を取得できませんでした。")
        return
    
    # フォームを使ってプルダウンが閉じないようにする
    with st.form("room_selection_form"):
        st.session_state.selected_room_names_temp = st.multiselect(
            "比較したいルームを選択 (複数選択可):", 
            options=list(st.session_state.room_map_data.keys()),
            default=st.session_state.selected_room_names,
            key="multiselect_key"
        )
        submit_button = st.form_submit_button("表示する")

    if submit_button:
        st.session_state.selected_room_names = st.session_state.selected_room_names_temp
        st.rerun()

    if not st.session_state.selected_room_names:
        st.warning("最低1つのルームを選択してください。")
        return

    # --- Real-time Dashboard Section ---
    st.header("3. リアルタイムダッシュボード")
    st.info("5秒ごとに自動更新されます。")

    # イベント期間と残り時間のレイアウト
    with st.container(border=True):
        st.subheader("イベント情報")
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.write("イベント期間")
            st.write(f"**{event_period_str}**")

        with col2:
            st.write("残り時間")
            time_placeholder = st.empty()

    current_time = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    st.write(f"最終更新日時 (日本時間): {current_time}")
    
    onlives_rooms = get_onlives_rooms()

    data_to_display = []
    final_remain_time = None
    
    # 選択されたルームが存在するかチェック
    if st.session_state.selected_room_names:
        
        for room_name in st.session_state.selected_room_names:
            try:
                # `room_map_data`に存在しないキーを参照する可能性を考慮
                if room_name not in st.session_state.room_map_data:
                    st.error(f"選択されたルーム名 '{room_name}' が見つかりません。リストを更新してください。")
                    continue
                    
                room_id = st.session_state.room_map_data[room_name]['room_id']
                room_info = get_room_event_info(room_id)
            
                if not isinstance(room_info, dict):
                    st.warning(f"ルームID {room_id} のデータが不正な形式です。スキップします。")
                    continue
            
                rank_info = None
                remain_time_sec = None

                if 'ranking' in room_info and isinstance(room_info['ranking'], dict):
                    rank_info = room_info['ranking']
                    remain_time_sec = room_info.get('remain_time')
                elif 'event_and_support_info' in room_info and isinstance(room_info['event_and_support_info'], dict):
                    event_info = room_info['event_and_support_info']
                    if 'ranking' in event_info and isinstance(event_info['ranking'], dict):
                        rank_info = event_info['ranking']
                        remain_time_sec = event_info.get('remain_time')
                elif 'event' in room_info and isinstance(room_info['event'], dict):
                    event_data = room_info['event']
                    if 'ranking' in event_data and isinstance(event_data['ranking'], dict):
                        rank_info = event_data['ranking']
                        remain_time_sec = event_data.get('remain_time')
                
                # 必要なデータがすべて存在するかチェック
                if rank_info and 'point' in rank_info and remain_time_sec is not None:
                    data_to_display.append({
                        "ライブ中": "🔴" if int(room_id) in onlives_rooms else "",
                        "ルーム名": room_name,
                        "現在の順位": rank_info.get('rank', 'N/A'),
                        "現在のポイント": rank_info.get('point', 'N/A'),
                        "下位とのポイント差": rank_info.get('lower_gap', 'N/A') if rank_info.get('lower_rank', 0) > 0 else 0,
                        "下位の順位": rank_info.get('lower_rank', 'N/A')
                    })
                    
                    if final_remain_time is None: # 一度だけ残り時間を設定
                        final_remain_time = remain_time_sec

                else:
                    st.warning(f"ルーム名 '{room_name}' のランキング情報が不完全です。スキップします。")

            except Exception as e:
                st.error(f"データ処理中に予期せぬエラーが発生しました（ルーム名: {room_name}）。エラー: {e}")
                continue

        if data_to_display:
            df = pd.DataFrame(data_to_display)
            
            # 順位でソート
            df['現在の順位'] = pd.to_numeric(df['現在の順位'], errors='coerce')
            df = df.sort_values(by='現在の順位', ascending=True, na_position='last').reset_index(drop=True)

            st.subheader("📊 比較対象ルームのステータス")
            
            # DataFrameの列が期待通りに存在するかチェックしてからスタイルを適用
            required_cols = ['現在のポイント', '下位とのポイント差']
            if all(col in df.columns for col in required_cols):
                try:
                    df['現在のポイント'] = pd.to_numeric(df['現在のポイント'], errors='coerce')
                    df['下位とのポイント差'] = pd.to_numeric(df['下位とのポイント差'], errors='coerce')
                    
                    styled_df = df.style.highlight_max(axis=0, subset=['現在のポイント']).format(
                        {'現在のポイント': '{:,}', '下位とのポイント差': '{:,}'}
                    )
                    st.dataframe(styled_df, use_container_width=True, hide_index=True) # インデックス非表示
                except Exception as e:
                    st.error(f"データフレームのスタイル適用中にエラーが発生しました: {e}")
                    st.dataframe(df, use_container_width=True, hide_index=True) # インデックス非表示
            else:
                st.dataframe(df, use_container_width=True, hide_index=True) # インデックス非表示
                st.warning("データに不備があるため、ハイライトやフォーマットを適用できませんでした。")

            st.subheader("📈 ポイントと順位の比較")
            
            if '現在のポイント' in df.columns:
                fig_points = px.bar(df, x="ルーム名", y="現在のポイント", 
                                    title="各ルームの現在のポイント", 
                                    color="ルーム名",
                                    hover_data=["現在の順位", "下位とのポイント差"],
                                    labels={"現在のポイント": "ポイント", "ルーム名": "ルーム名"})
                st.plotly_chart(fig_points, use_container_width=True)
            else:
                st.warning("ポイントデータが不完全なため、ポイントグラフを表示できません。")

            if len(st.session_state.selected_room_names) > 1 and "下位とのポイント差" in df.columns:
                df['下位とのポイント差'] = pd.to_numeric(df['下位とのポイント差'], errors='coerce')
                fig_gap = px.bar(df, x="ルーム名", y="下位とのポイント差", 
                                title="下位とのポイント差", 
                                color="ルーム名",
                                hover_data=["現在の順位", "現在のポイント"],
                                labels={"下位とのポイント差": "ポイント差", "ルーム名": "ルーム名"})
                st.plotly_chart(fig_gap, use_container_width=True)
            elif len(st.session_state.selected_room_names) > 1:
                st.warning("ポイント差データが不完全なため、ポイント差グラフを表示できません。")

        if final_remain_time is not None:
            remain_time_readable = str(datetime.timedelta(seconds=final_remain_time))
            time_placeholder.metric(label="イベント終了まで", value=remain_time_readable)
        else:
            time_placeholder.info("残り時間情報を取得できませんでした。")
    
    time.sleep(5)
    st.rerun()

if __name__ == "__main__":
    main()