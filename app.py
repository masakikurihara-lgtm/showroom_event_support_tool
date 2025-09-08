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
        except ValueError: # JSONDecodeError
            st.error(f"APIからのJSONデコードに失敗しました: {response.text}")
            return []
            
    return events

# ランキングAPIの候補を定義
# room_idが含まれる可能性が高いものを優先
RANKING_API_CANDIDATES = [
    "https://www.showroom-live.com/api/event/ranking?event_id={event_id}&page={page}",
    "https://www.showroom-live.com/api/event/room_ranking?event_id={event_id}&page={page}",
    "https://www.showroom-live.com/api/event/{event_url_key}/ranking?page={page}",
    "https://www.showroom-live.com/api/event/rank_list?event_id={event_id}&page={page}",
]

def get_event_ranking_with_room_id(event_url_key, event_id, max_pages=10):
    """Fetches ranking data including room_id by trying multiple API endpoints."""
    st.info("複数のAPIエンドポイントを試行して、ルームIDを含むランキングデータを取得します。")
    for base_url in RANKING_API_CANDIDATES:
        try:
            all_ranking_data = []
            for page in range(1, max_pages + 1):
                url = base_url.format(event_url_key=event_url_key, event_id=event_id, page=page)
                
                response = requests.get(url, headers=HEADERS, timeout=10)
                if response.status_code == 404:
                    st.warning(f"URLが有効ではありませんでした: {url}")
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
                
                all_ranking_data.extend(ranking_list)
            
            # 取得したデータにroom_idが含まれているかチェック
            if all_ranking_data and 'room_id' in all_ranking_data[0]:
                st.success(f"ランキングデータ取得に成功しました。使用したURL: {base_url}")
                return all_ranking_data
            else:
                st.warning(f"取得したデータにルームIDが含まれていませんでした。次の候補を試します。使用したURL: {base_url}")
                continue # Try next URL
        
        except requests.exceptions.RequestException as e:
            st.error(f"API呼び出し中にエラー: {e}")
            continue

    return None

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

# --- Main Application Logic ---

def main():
    st.title("🎤 SHOWROOMイベント可視化ツール")
    st.write("ライバーとリスナーのための、イベント順位とポイント差をリアルタイムで可視化するツールです。")
    
    # --- Event Selection Section ---
    st.header("1. イベントを選択")
    events = get_events()
    if not events:
        st.warning("現在開催中のイベントが見つかりませんでした。")
        return

    event_options = {event['event_name']: event for event in events}
    selected_event_name = st.selectbox(
        "イベント名を選択してください:", 
        options=list(event_options.keys())
    )
    
    selected_event_data = event_options[selected_event_name]
    selected_event_key = selected_event_data.get('event_url_key', '')
    selected_event_id = selected_event_data.get('event_id')
    st.info(f"選択されたイベント: **{selected_event_name}**")
    
    # --- Room Selection Section ---
    st.header("2. 比較したいルームを選択")
    
    # ルームIDを含むランキングデータを取得
    ranking_data = get_event_ranking_with_room_id(selected_event_key, selected_event_id)
    if not ranking_data:
        st.warning("このイベントの参加者情報を取得できませんでした。ルームIDが含まれるAPIが見つかりませんでした。")
        return
        
    rooms = ranking_data
    if not rooms:
        st.warning("このイベントにはまだ参加者がいません。")
        return
        
    room_options = {}
    for room in rooms:
        if 'room_id' in room and 'room_name' in room:
            room_options[room['room_name']] = room['room_id']
        elif 'room_id' in room and 'user_name' in room:
            room_options[room['user_name']] = room['room_id']

    if not room_options:
        st.warning("参加者リストから有効なルーム情報を取得できませんでした。")
        return
    
    selected_room_names = st.multiselect(
        "比較したいルームを選択 (複数選択可):", 
        options=list(room_options.keys()),
        default=[list(room_options.keys())[0]]
    )
    
    if not selected_room_names:
        st.warning("最低1つのルームを選択してください。")
        return

    selected_room_ids = [room_options[name] for name in selected_room_names]

    # --- Real-time Dashboard Section ---
    st.header("3. リアルタイムダッシュボード")
    st.info("5秒ごとに自動更新されます。")
    
    dashboard_placeholder = st.empty()
    
    JST = pytz.timezone('Asia/Tokyo')
    
    while True:
        with dashboard_placeholder.container():
            current_time = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
            st.write(f"最終更新日時 (日本時間): {current_time}")
            
            data_to_display = []
            
            for room_id in selected_room_ids:
                room_info = get_room_event_info(room_id)
                if room_info and 'ranking' in room_info:
                    rank_info = room_info['ranking']
                    remain_time_sec = room_info.get('remain_time', 0)
                    remain_time_str = str(datetime.timedelta(seconds=remain_time_sec))

                    room_name = [name for name, id in room_options.items() if id == room_id][0]

                    data_to_display.append({
                        "ルーム名": room_name,
                        "現在の順位": rank_info['rank'],
                        "現在のポイント": rank_info['point'],
                        "下位とのポイント差": rank_info['lower_gap'] if 'lower_gap' in rank_info and rank_info['lower_rank'] > 0 else 0,
                        "下位の順位": rank_info['lower_rank'] if 'lower_rank' in rank_info else "N/A",
                        "残り時間": remain_time_str,
                    })
            
            if data_to_display:
                df = pd.DataFrame(data_to_display)
                
                df_sorted = df.sort_values(by="現在の順位").reset_index(drop=True)
                
                st.subheader("📊 比較対象ルームのステータス")
                st.dataframe(df_sorted.style.highlight_max(axis=0, subset=['現在のポイント']).format(
                    {'現在のポイント': '{:,}', '下位とのポイント差': '{:,}'}
                ), use_container_width=True)

                st.subheader("📈 ポイントと順位の比較")
                
                fig_points = px.bar(df_sorted, x="ルーム名", y="現在のポイント", 
                                    title="各ルームの現在のポイント", 
                                    color="ルーム名",
                                    hover_data=["現在の順位", "下位とのポイント差"],
                                    labels={"現在のポイント": "ポイント", "ルーム名": "ルーム名"})
                st.plotly_chart(fig_points, use_container_width=True)

                if len(selected_room_names) > 1 and "下位とのポイント差" in df_sorted.columns:
                    fig_gap = px.bar(df_sorted, x="ルーム名", y="下位とのポイント差", 
                                    title="下位とのポイント差", 
                                    color="ルーム名",
                                    hover_data=["現在の順位", "現在のポイント"],
                                    labels={"下位とのポイント差": "ポイント差", "ルーム名": "ルーム名"})
                    st.plotly_chart(fig_gap, use_container_width=True)

            else:
                st.warning("選択されたルームの情報を取得できませんでした。APIのレスポンス形式が変更された可能性があります。")

        time.sleep(5)

if __name__ == "__main__":
    main()