import requests
import datetime
import yaml
import json

def load_api_keys(filename="config.yaml"):
    with open(filename, "r") as f:
        return yaml.safe_load(f)
    
# Notion Configuration 설정
config = load_api_keys('config.yaml')
NOTION_API_KEY = config['NOTION_API_KEY']
NOTION_DATABASE_ID = config['NOTION_DATABASE_ID']

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
} 

TOPICS = config['TOPICS']
CONFIDENCE_LEVELS = config['CONFIDENCE_LEVELS']



def get_daily_entry_count(date_str):
    """해당 날짜의 기존 항목 수를 계산"""
    query = {"filter": {"property": "Date", "date": {"equals": date_str}}}
    response = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query",
        headers=HEADERS,
        json=query
    )
    return len(response.json().get("results", [])) if response.status_code == 200 else 0

def get_or_create_daily_entry(date_str, summary):
    """날짜와 순번에 해당하는 데이터베이스 항목 생성 또는 가져오기"""
    entry_count = get_daily_entry_count(date_str) + 1
    index_str = f"{date_str} ({entry_count})"
    
    query = {
        "filter": {
            "property": "Index",
            "rich_text": {"equals": index_str}
        }
    }
    
    response = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query", 
        headers=HEADERS, 
        json=query
    )
    
    if response.status_code != 200:
        print(f"데이터베이스 쿼리 실패: {response.text}")
        return None
    
    results = response.json().get("results", [])
    
    # 해당 날짜의 페이지가 이미 있는 경우
    if results:
        return results[0]["id"]
    
    # 새 항목 생성
    data = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Index": {"title": [{"text": {"content": index_str}}]},
            "Date": {"date": {"start": date_str}},
            "Topics Covered": {"multi_select": []}, # 초기에 빈 값으로 생성
            "Confidence Level": {"select": {"name": "Unknown"}},
            "Summary": {"rich_text": [{"text": {"content": summary}}]},
            "Follow-up Needed": {"checkbox": False}
        }
    }
    
    response = requests.post(
        "https://api.notion.com/v1/pages", 
        headers=HEADERS, 
        json=data
    )
    
    if response.status_code != 200:
        print(f"페이지 생성 실패: {response.text}")
        return None
    
    return response.json()["id"]

def update_page_properties(page_id, topics, confidence_level):
    """페이지 속성(properties) 업데이트"""
    update_data = {
        "properties": {
            "Topics Covered": {"multi_select": [{"name": topic} for topic in topics if topic]},
            "Confidence Level": {"select": {"name": confidence_level}}
        }
    }
    
    response = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}", 
        headers=HEADERS, 
        json=update_data
    )
    
    if response.status_code != 200:
        print(f"페이지 속성 업데이트 실패: {response.text}")
        return False
    
    return True

def add_content_to_page(page_id, conversation_log, awkward_expressions, corrections, timestamp):
    """페이지에 대화 로그, 어색한 표현, 교정 내용 추가"""
    blocks = [
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Conversation Log"}}]}
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"({timestamp})\n"}}]}
        }
    ]
    
    for line in conversation_log.split('\n'):
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": line}}]}
        })
    
    if awkward_expressions:
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Awkward Expressions"}}]}
        })
        for expr in awkward_expressions.split('\n'):
            if expr.strip():
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": expr.strip()}}]}
                })
    
    if corrections:
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Corrections"}}]}
        })
        for corr in corrections.split('\n'):
            if corr.strip():
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": corr.strip()}}]}
                })
    
    response = requests.patch(
        f"https://api.notion.com/v1/blocks/{page_id}/children",
        headers=HEADERS,
        json={"children": blocks}
    )
    
    if response.status_code != 200:
        print(f"페이지 내용 추가 실패: {response.text}")
        return False
    
    return True

def save_conversation(conversation_log, summary, awkward_expressions="", corrections="", topics=None, confidence_level="Unknown"):
    """대화 내용을 데이터베이스에 저장"""
    topics = topics or ["Daily Life"]
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 페이지 생성 또는 가져오기
    page_id = get_or_create_daily_entry(date_str, summary)
    if not page_id:
        print("페이지 생성 실패")
        return False
    
    # 페이지 속성 업데이트
    if not update_page_properties(page_id, topics, confidence_level):
        print("속성 업데이트 실패")
        return False
    
    # 페이지 내부 내용 추가
    if not add_content_to_page(page_id, conversation_log, awkward_expressions, corrections, timestamp):
        print("내용 추가 실패")
        return False
    
    return True

def test_save_conversation():
    """대화 저장 기능 테스트"""
    # result = save_conversation(
    #     conversation_log="User: How are you today?\nAI: I'm doing well, thank you for asking! How about you?",
    #     summary="Quick greeting exchange",
    #     awkward_expressions="'How are you today' - sounds stiff\n'I'm fine' - too formal",
    #     corrections="Try 'How’s it going?' instead\nUse 'I’m good, thanks!' for a natural response",
    #     topics=["Greetings", "Daily Life"],
    #     confidence_level="High"
    # )
    
    result = save_conversation(
    conversation_log="User: Hi, how you doing this morning?\nAI: Hey! I’m good, thanks. How about you?\nUser: I good too. Didn’t sleep much though.\nAI: Oh, rough night? What kept you up?",
    summary="Morning greeting with a friend",
    awkward_expressions="'How you doing' - Missing 'are', sounds incomplete\n'I good too' - Grammar error, missing 'am'",
    corrections="Say 'How are you doing?' for natural flow\nUse 'I’m good too' instead of 'I good too'",
    topics=["Greetings", "Daily Life"],
    confidence_level="Medium"
)
    
    print("✅ 대화 저장 성공!" if result else "❌ 대화 저장 실패!")

if __name__ == "__main__":
    test_save_conversation()