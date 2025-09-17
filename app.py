import streamlit as st
import requests
import pandas as pd
import time
import datetime
import plotly.express as px
import pytz
from streamlit_autorefresh import st_autorefresh
from datetime import timedelta
import logging


# Set page configuration
st.set_page_config(
    page_title="SHOWROOM Event Dashboard",
    page_icon="🎤",
    layout="wide",
)

HEADERS = {"User-Agent": "Mozilla/5.0"}
JST = pytz.timezone('Asia/Tokyo')

@st.cache_data(ttl=3600)
def get_events():
    """
    開催中および終了済みのイベントリストを取得する。
    終了済みイベントには "＜終了＞" という接頭辞を付ける。
    """
    all_events = []
    # status=1 (開催中) と status=4 (終了済み) の両方を取得
    for status in [1, 4]:
        page = 1
        # 各ステータスで最大10ページまで取得
        for _ in range(10):
            url = f"https://www.showroom-live.com/api/event/search?status={status}&page={page}"
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
                    break  # イベントがなくなったらループを抜ける

                # 既存のフィルタリングロジックを適用
                filtered_page_events = [
                    event for event in page_events 
                    if event.get("show_ranking") is not False and event.get("is_event_block") is not True
                ]
                
                # 終了済みイベントの場合、イベント名に接頭辞を追加
                if status == 4:
                    for event in filtered_page_events:
                        event['event_name'] = f"＜終了＞ {event['event_name']}"

                all_events.extend(filtered_page_events)
                page += 1
            except requests.exceptions.RequestException as e:
                st.error(f"イベントデータ取得中にエラーが発生しました (status={status}): {e}")
                break
            except ValueError:
                st.error(f"APIからのJSONデコードに失敗しました: {response.text}")
                break
    return all_events


RANKING_API_CANDIDATES = [
    "https://www.showroom-live.com/api/event/{event_url_key}/ranking?page={page}",
    "https://www.showroom-live.com/api/event/ranking?event_id={event_id}&page={page}",
]

@st.cache_data(ttl=300)
def get_event_ranking_with_room_id(event_url_key, event_id, max_pages=10):
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
    url = f"https://www.showroom-live.com/api/room/event_and_support?room_id={room_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        # このエラーはmain()でキャッチし、よりユーザーフレンドリーなメッセージを表示する
        st.error(f"ルームID {room_id} のデータ取得中にエラーが発生しました: {e}")
        return None

@st.cache_data(ttl=30)
def get_gift_list(room_id):
    url = f"https://www.showroom-live.com/api/live/gift_list?room_id={room_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        data = response.json()
        gift_list_map = {}
        for gift in data.get('normal', []) + data.get('special', []):
            try:
                point_value = int(gift.get('point', 0))
            except (ValueError, TypeError):
                point_value = 0
            gift_list_map[str(gift['gift_id'])] = {
                'name': gift.get('gift_name', 'N/A'),
                'point': point_value,
                'image': gift.get('image', '')
            }
        return gift_list_map
    except requests.exceptions.RequestException as e:
        st.error(f"ルームID {room_id} のギフトリスト取得中にエラーが発生しました: {e}")
        return {}

if "gift_log_cache" not in st.session_state:
    st.session_state.gift_log_cache = {}

def get_and_update_gift_log(room_id):
    url = f"https://www.showroom-live.com/api/live/gift_log?room_id={room_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        new_gift_log = response.json().get('gift_log', [])
        
        if room_id not in st.session_state.gift_log_cache:
            st.session_state.gift_log_cache[room_id] = []
        
        existing_log = st.session_state.gift_log_cache[room_id]
        
        if new_gift_log:
            existing_log_set = {(log.get('gift_id'), log.get('created_at'), log.get('num')) for log in existing_log}
            
            for log in new_gift_log:
                log_key = (log.get('gift_id'), log.get('created_at'), log.get('num'))
                if log_key not in existing_log_set:
                    existing_log.append(log)
        
        st.session_state.gift_log_cache[room_id].sort(key=lambda x: x.get('created_at', 0), reverse=True)
        
        return st.session_state.gift_log_cache[room_id]
        
    except requests.exceptions.RequestException as e:
        st.warning(f"ルームID {room_id} のギフトログ取得中にエラーが発生しました。配信中か確認してください: {e}")
        return st.session_state.gift_log_cache.get(room_id, [])

# ▼▼▼ 修正箇所(1): premium_room_typeも取得するように修正 ▼▼▼
def get_onlives_rooms():
    onlives = {}
    try:
        url = "https://www.showroom-live.com/api/live/onlives"
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()
        data = response.json()
        all_lives = []
        if isinstance(data, dict):
            if 'onlives' in data and isinstance(data['onlives'], list):
                for genre_group in data['onlives']:
                    if 'lives' in genre_group and isinstance(genre_group['lives'], list):
                        all_lives.extend(genre_group['lives'])
            for live_type in ['official_lives', 'talent_lives', 'amateur_lives']:
                if live_type in data and isinstance(data.get(live_type), list):
                    all_lives.extend(data[live_type])
        for room in all_lives:
            room_id = None
            started_at = None
            premium_room_type = 0
            if isinstance(room, dict):
                room_id = room.get('room_id')
                started_at = room.get('started_at')
                premium_room_type = room.get('premium_room_type', 0)
                if room_id is None and 'live_info' in room and isinstance(room['live_info'], dict):
                    room_id = room['live_info'].get('room_id')
                    started_at = room['live_info'].get('started_at')
                    premium_room_type = room['live_info'].get('premium_room_type', 0)
                if room_id is None and 'room' in room and isinstance(room['room'], dict):
                    room_id = room['room'].get('room_id')
                    started_at = room['room'].get('started_at')
                    premium_room_type = room['room'].get('premium_room_type', 0)
            if room_id and started_at is not None:
                try:
                    onlives[int(room_id)] = {'started_at': started_at, 'premium_room_type': premium_room_type}
                except (ValueError, TypeError):
                    continue
    except requests.exceptions.RequestException as e:
        st.warning(f"配信情報取得中にエラーが発生しました: {e}")
    except (ValueError, AttributeError):
        st.warning("配信情報のJSONデコードまたは解析に失敗しました。")
    return onlives
# ▲▲▲ 修正箇所(1) ここまで ▲▲▲

def get_rank_color(rank):
    """
    ランキングに応じたカラーコードを返す
    Plotlyのデフォルトカラーを参考に設定
    """
    colors = px.colors.qualitative.Plotly
    if rank is None:
        return "#A9A9A9"  # DarkGray
    try:
        rank_int = int(rank)
        if rank_int <= 0:
            return colors[0]
        return colors[(rank_int - 1) % len(colors)]
    except (ValueError, TypeError):
        return "#A9A9A9"
    
def main():
    st.markdown("<h1 style='font-size:2.5em;'>🎤 SHOWROOM Event Dashboard</h1>", unsafe_allow_html=True)
    st.write("イベント順位やポイント差、スペシャルギフトの履歴などを、リアルタイムで可視化するツールです。")

    if "room_map_data" not in st.session_state:
        st.session_state.room_map_data = None
    if "selected_event_name" not in st.session_state:
        st.session_state.selected_event_name = None
    if "selected_room_names" not in st.session_state:
        st.session_state.selected_room_names = []
    if "multiselect_default_value" not in st.session_state:
        st.session_state.multiselect_default_value = []
    if "multiselect_key_counter" not in st.session_state:
        st.session_state.multiselect_key_counter = 0
    if "show_dashboard" not in st.session_state:
        st.session_state.show_dashboard = False

    st.markdown("<h2 style='font-size:2em;'>1. イベントを選択</h2>", unsafe_allow_html=True)
    events = get_events()
    if not events:
        st.warning("表示可能なイベントが見つかりませんでした。")
        return

    event_options = {event['event_name']: event for event in events}
    selected_event_name = st.selectbox(
        "イベント名を選択してください:", 
        options=list(event_options.keys()), key="event_selector")
    
    st.markdown(
        "<p style='font-size:12px; margin: -10px 0px 20px 0px; color:#a1a1a1;'>※ランキング型イベントが対象になります。ただし、ブロック型は対象外になります。<br />※終了済みイベントは、イベント終了日の約1ヶ月後を目処に対象から削除されます。また、ポイントの表示は、イベント終了日の翌々日の12:00頃を目処にクリアされます。</p>",
        unsafe_allow_html=True
    )

    if not selected_event_name:
        st.warning("イベントを選択してください。")
        return

    selected_event_data = event_options.get(selected_event_name)
    event_url = f"https://www.showroom-live.com/event/{selected_event_data.get('event_url_key')}"
    started_at_dt = datetime.datetime.fromtimestamp(selected_event_data.get('started_at'), JST)
    ended_at_dt = datetime.datetime.fromtimestamp(selected_event_data.get('ended_at'), JST)
    event_period_str = f"{started_at_dt.strftime('%Y/%m/%d %H:%M')} - {ended_at_dt.strftime('%Y/%m/%d %H:%M')}"
    st.info(f"選択されたイベント: **{selected_event_name}**")

    st.markdown("<h2 style='font-size:2em;'>2. 比較したいルームを選択</h2>", unsafe_allow_html=True)
    selected_event_key = selected_event_data.get('event_url_key', '')
    selected_event_id = selected_event_data.get('event_id')

    # --- ▼▼▼ ここからが修正箇所(1) ▼▼▼ ---
    # イベントを変更した場合、「上位10ルームまでを選択」のチェックボックスも初期化する
    if st.session_state.selected_event_name != selected_event_name or st.session_state.room_map_data is None:
        with st.spinner('イベント参加者情報を取得中...'):
            st.session_state.room_map_data = get_event_ranking_with_room_id(selected_event_key, selected_event_id)
        st.session_state.selected_event_name = selected_event_name
        st.session_state.selected_room_names = []
        st.session_state.multiselect_default_value = []
        st.session_state.multiselect_key_counter += 1
        # チェックボックスのキーが存在すればFalseに設定
        if 'select_top_10_checkbox' in st.session_state:
            st.session_state.select_top_10_checkbox = False
        st.session_state.show_dashboard = False
        st.rerun()
    # --- ▲▲▲ ここまでが修正箇所(1) ▲▲▲ ---

    room_count_text = ""
    if st.session_state.room_map_data:
        room_count = len(st.session_state.room_map_data)
        room_count_text = f" （現在{room_count}ルーム参加）"
    st.markdown(f"**▶ [イベントページへ移動する]({event_url})**{room_count_text}", unsafe_allow_html=True)

    if not st.session_state.room_map_data:
        st.warning("このイベントの参加者情報を取得できませんでした。")
        return

    with st.form("room_selection_form"):
        select_top_10 = st.checkbox(
            "上位10ルームまでを選択（**※チェックされている場合はこちらが優先されます**）", 
            key="select_top_10_checkbox")
        room_map = st.session_state.room_map_data
        sorted_rooms = sorted(room_map.items(), key=lambda item: item[1].get('point', 0), reverse=True)
        room_options = [room[0] for room in sorted_rooms]
        top_10_rooms = room_options[:10]
        selected_room_names_temp = st.multiselect(
            "比較したいルームを選択 (複数選択可):", options=room_options,
            default=st.session_state.multiselect_default_value,
            key=f"multiselect_{st.session_state.multiselect_key_counter}")
        submit_button = st.form_submit_button("表示する")
        if submit_button:
            if st.session_state.select_top_10_checkbox:
                st.session_state.selected_room_names = top_10_rooms
                st.session_state.multiselect_default_value = top_10_rooms
                st.session_state.multiselect_key_counter += 1
            else:
                st.session_state.selected_room_names = selected_room_names_temp
                st.session_state.multiselect_default_value = selected_room_names_temp
            st.session_state.show_dashboard = True
            st.rerun()

    if st.session_state.show_dashboard:
        if not st.session_state.selected_room_names:
            st.warning("最低1つのルームを選択してください。")
            return

        st.markdown("<h2 style='font-size:2em;'>3. リアルタイムダッシュボード</h2>", unsafe_allow_html=True)
        st_autorefresh(interval=7000, key="refresh_dashboard")
        
        st.info("7秒ごとに自動更新されます。")
        
        # --- 修正開始 ---
        # ポイントが確定しているかを判断するロジック
        event_info_from_all_events = next((e for e in all_events if e['event_id'] == selected_event_id), None)
        is_closed = event_info_from_all_events.get('is_closed', False) if event_info_from_all_events else False
        event_end_time_ts = event_info_from_all_events.get('ended_at') if event_info_from_all_events else None
        
        is_event_ended = event_end_time_ts and datetime.datetime.fromtimestamp(event_end_time_ts, JST) < datetime.datetime.now(JST)

        # ランキング情報を取得
        room_map = st.session_state.room_map_data
        
        if room_map:
            df = pd.DataFrame(room_map).T.reset_index().rename(columns={'index': 'ルーム名', 'rank': '現在の順位', 'point': '現在のポイント'})
            df = df.sort_values(by='現在の順位', ascending=True)

            if is_event_ended and not is_closed:
                df['現在のポイント'] = '集計中'
            
            # --- 修正終了 ---

            # 差分を計算するロジック（変更なし）
            if len(st.session_state.selected_room_names) > 1:
                # 順位でソート
                df_sorted = df.sort_values(by='現在の順位', ascending=True)

                # 上位とのポイント差を計算
                df_sorted['上位とのポイント差'] = df_sorted['現在のポイント'].diff(periods=-1).abs()
                
                # 下位とのポイント差を計算
                df_sorted['下位とのポイント差'] = df_sorted['現在のポイント'].diff(periods=1).abs()

                df_sorted.loc[df_sorted['現在の順位'] == 1, '上位とのポイント差'] = 'N/A'
                df_sorted.loc[df_sorted['現在の順位'] == df_sorted['現在の順位'].max(), '下位とのポイント差'] = 'N/A'
                
                df = df_sorted
            
            # ダッシュボード表示
            with st.container(border=True):
                col1, col2 = st.columns([1, 1])
                with col1:
                    st.components.v1.html(f"""
                        <div style="font-weight: bold; font-size: 1.5rem; color: #333333; line-height: 1.2; padding-bottom: 15px;">イベント期間</div>
                        <div style="font-weight: bold; font-size: 1.1rem; color: #333333; line-height: 1.2;">{event_period_str}</div>
                    """, height=80)
                with col2:
                    st.components.v1.html(f"""
                        <div style="font-weight: bold; font-size: 1.5rem; color: #333333; line-height: 1.2; padding-bottom: 15px;">残り時間</div>
                        <div style="font-weight: bold; font-size: 1.1rem; line-height: 1.2;">
                            <span id="sr_countdown_timer_in_col" style="color: #4CAF50;" data-end="{int(ended_at_dt.timestamp() * 1000)}">計算中...</span>
                        </div>
                        </div>
                        <script>
                            (function() {{
                                function start() {{
                                    const timer = document.getElementById('sr_countdown_timer_in_col');
                                    if (!timer) return false;
                                    const END = parseInt(timer.dataset.end, 10);
                                    if (isNaN(END)) return false;
                                    if (window._sr_countdown_interval_in_col) clearInterval(window._sr_countdown_interval_in_col);

                                    function pad(n) {{ return String(n).padStart(2,'0'); }}
                                    function formatMs(ms) {{
                                        if (ms < 0) ms = 0;
                                        let s = Math.floor(ms / 1000), days = Math.floor(s / 86400);
                                        s %= 86400;
                                        let hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
                                        if (days > 0) return `${{days}}d ${{pad(hh)}}:${{pad(mm)}}:${{pad(ss)}}`;
                                        return `${{pad(hh)}}:${{pad(mm)}}:${{pad(ss)}}`;
                                    }}
                                    
                                    function update() {{
                                        const diff = END - Date.now();
                                        if (diff <= 0) {{
                                            timer.textContent = 'イベント終了';
                                            timer.style.color = '#808080';
                                            clearInterval(window._sr_countdown_interval_in_col);
                                            return;
                                        }}
                                        timer.textContent = formatMs(diff);
                                        const totalSeconds = Math.floor(diff / 1000);
                                        if (totalSeconds <= 3600) timer.style.color = '#ff4b4b';
                                        else if (totalSeconds <= 10800) timer.style.color = '#ffa500';
                                        else timer.style.color = '#4CAF50';
                                    }}

                                    update();
                                    window._sr_countdown_interval_in_col = setInterval(update, 1000);
                                    return true;
                                }}
                                if (document.readyState === 'loading') window.addEventListener('DOMContentLoaded', start);
                                else start();
                            })();
                        </script>
                    """, height=80)
            
            # 選択されたルームのデータフレーム
            df_selected_rooms = df[df['ルーム名'].isin(st.session_state.selected_room_names)].copy()
            
            if not df_selected_rooms.empty:
                # '現在のポイント'が「集計中」でない場合のみグラフを表示
                if not (df_selected_rooms['現在のポイント'] == '集計中').any():
                    # ポイント推移グラフ
                    st.markdown("<h3 style='font-size:1.5em;'>📈 ポイント推移グラフ</h3>", unsafe_allow_html=True)
                    # この部分は、リアルタイムのポイント推移データを取得するロジックを実装する必要があります
                    st.info("この機能は、過去のポイント推移を表示するために、ここに新しいロジックを実装する必要があります。")
                else:
                    st.info("イベントは終了し、ポイント集計中のため、ポイント推移グラフは表示されません。")
                
                # 順位とポイント差の表
                st.markdown("<h3 style='font-size:1.5em;'>📊 リアルタイムランキング</h3>", unsafe_allow_html=True)
                
                display_cols = ['現在の順位', 'ルーム名', '現在のポイント']
                if len(st.session_state.selected_room_names) > 1:
                    if '上位とのポイント差' in df_selected_rooms.columns:
                        display_cols.append('上位とのポイント差')
                    if '下位とのポイント差' in df_selected_rooms.columns:
                        display_cols.append('下位とのポイント差')

                st.dataframe(
                    df_selected_rooms[display_cols], 
                    use_container_width=True, 
                    hide_index=True
                )

                # ランキング棒グラフ（ポイントが数値の場合のみ）
                if not (df_selected_rooms['現在のポイント'] == '集計中').any():
                    df_selected_rooms['現在のポイント'] = pd.to_numeric(df_selected_rooms['現在のポイント'], errors='coerce')
                    df_selected_rooms = df_selected_rooms.sort_values(by='現在の順位')
                    
                    fig_points = px.bar(
                        df_selected_rooms, x="ルーム名", y="現在のポイント", title="選択ルームのポイント", color="ルーム名",
                        labels={"現在のポイント": "ポイント", "ルーム名": "ルーム名"}
                    )
                    st.plotly_chart(fig_points, use_container_width=True, key="points_chart")
                    
                    # 棒グラフ（ポイント差）
                    if len(st.session_state.selected_room_names) > 1:
                        st.markdown("<h3 style='font-size:1.5em;'>ポイント差グラフ</h3>", unsafe_allow_html=True)
                        
                        df_gaps = df_selected_rooms.set_index('ルーム名')
                        color_map = {name: get_rank_color(df_gaps.loc[name, '現在の順位']) for name in st.session_state.selected_room_names}
                        
                        if "上位とのポイント差" in df_gaps.columns:
                            fig_upper_gap = px.bar(
                                df_gaps.dropna(subset=['上位とのポイント差']).reset_index(), 
                                x="ルーム名", y="上位とのポイント差", title="上位とのポイント差", color="ルーム名",
                                color_discrete_map=color_map, hover_data=["現在の順位", "現在のポイント"],
                                labels={"上位とのポイント差": "ポイント差", "ルーム名": "ルーム名"}
                            )
                            st.plotly_chart(fig_upper_gap, use_container_width=True, key="upper_gap_chart")

                        if "下位とのポイント差" in df_gaps.columns:
                            fig_lower_gap = px.bar(
                                df_gaps.dropna(subset=['下位とのポイント差']).reset_index(), 
                                x="ルーム名", y="下位とのポイント差", title="下位とのポイント差", color="ルーム名",
                                color_discrete_map=color_map, hover_data=["現在の順位", "現在のポイント"],
                                labels={"下位とのポイント差": "ポイント差", "ルーム名": "ルーム名"}
                            )
                            st.plotly_chart(fig_lower_gap, use_container_width=True, key="lower_gap_chart")

            else:
                st.warning("選択したルームのランキングデータを取得できませんでした。")

            # ファンリストとギフトログ
            for room_name in st.session_state.selected_room_names:
                room_id = st.session_state.room_map_data[room_name].get('room_id')
                if room_id:
                    event_info = get_room_event_info(room_id)
                    if event_info and event_info.get('room_is_live') and event_info.get('live_id'):
                        st.markdown(f"---")
                        st.markdown(f"### 🎉 **{room_name}** のスペシャルギフトとファンリスト", unsafe_allow_html=True)
                        st.info("この機能は、ファンリストやギフトログを表示するために、ここに新しいロジックを実装する必要があります。")

        else:
            st.warning("イベント参加者情報が取得できませんでした。時間をおいて再度お試しください。")

if __name__ == "__main__":
    main()