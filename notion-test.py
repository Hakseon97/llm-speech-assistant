import requests
import datetime
import json

# Notion API 설정
NOTION_API_KEY = "your_notion_api_key"
NOTION_DATABASE_ID = "your_notion_database_id"

# Notion에 테스트 데이터 저장 함수
def test_notion_api():
    today = datetime.date.today().strftime("%Y-%m-%d")
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    data = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Date": {"title": [{"text": {"content": today}}]},
            "Test": {"rich_text": [{"text": {"content": "Notion API 테스트 성공!"}}]}
        }
    }
    
    response = requests.post("https://api.notion.com/v1/pages", headers=headers, json=data)
    
    if response.status_code == 200:
        print("✅ Notion API 테스트 성공!")
    else:
        print(f"❌ Notion API 테스트 실패: {response.text}")

if __name__ == "__main__":
    test_notion_api()
