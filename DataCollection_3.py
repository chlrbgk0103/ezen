import requests
from bs4 import BeautifulSoup
import re
import oracledb as cx_Oracle


# ✅ 정책 상세 정보 섹션 크롤링
def crawl_all_sections(url):
    response = requests.get(url)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")

    data_store = {}
    titles = soup.find_all("strong", class_="tit")

    for title in titles:
        section_name = title.get_text(strip=True)
        table = title.find_next("table", class_="form-table form-resp-table")
        if table:
            section_data = {}
            rows = table.find_all("tr")
            for row in rows:
                ths = row.find_all("th")
                tds = row.find_all("td")
                for th, td in zip(ths, tds):
                    key = th.get_text(strip=True)
                    val = td.get_text(" ", strip=True).replace("\xa0", " ")
                    section_data[key] = val
            data_store[section_name] = section_data
    return data_store


# ✅ 질문 관련 섹션 찾기
def find_best_section(question, data_store):
    question_lower = question.lower()
    best_section = None
    max_matches = 0

    for section_name in data_store.keys():
        matches = sum(1 for word in section_name.lower().split() if word in question_lower)
        if matches > max_matches:
            max_matches = matches
            best_section = section_name

    return best_section


# ✅ 답변 생성
def generate_answer(question, data_store):
    section = find_best_section(question, data_store)
    if not section:
        return "관련된 정보를 찾을 수 없습니다."

    content = data_store.get(section, {})
    answer = f"{section}\n"
    for k, v in content.items():
        answer += f"{k}: {v}\n"
    return answer


# ✅ 정책 리스트 크롤링
def crawl_policy_list(list_url):
    response = requests.get(list_url)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")

    policy_items = soup.select("ul.policy-list li")
    policy_data = []

    for item in policy_items:
        try:
            category = item.select_one("span.bg-blue").get_text(strip=True)
            a_tag = item.select_one("a.tit.txt-over1")
            title = a_tag.get_text(strip=True)
            onclick = a_tag.get("onclick", "")
            class_attr = a_tag.get("class", [])

            policy_id = ""
            if "goView" in onclick:
                policy_id = onclick.replace("goView('", "").replace("');", "").strip()

            description = item.select_one("em.txt-over1").get_text(separator=" ", strip=True)

            policy_data.append({
                "category": category,
                "title": title,
                "policy_id": policy_id,
                "a_class": class_attr,
                "description": description
            })
        except Exception as e:
            print("파싱 오류:", e)
            continue

    return policy_data


# ✅ 정책 ID 기준 중복 체크 (file1 + file3 통합)
def load_saved_policy_ids_from_files(*file_paths):
    saved_ids = set()
    id_pattern = re.compile(r"plcyBizId=([^&\s]+)")
    for file_path in file_paths:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    match = id_pattern.search(line)
                    if match:
                        saved_ids.add(match.group(1).strip())
        except FileNotFoundError:
            pass
    return saved_ids


# ✅ 특수문자 제거
def remove_special_chars_with_space(text):
    cleaned = re.sub(r"[^가-힣a-zA-Z0-9\s]", " ", text)
    cleaned = " ".join(cleaned.split())
    return cleaned


# ✅ 파일3 저장
def save_policy_result_to_file(file_path, title, questions, data_store):
    with open(file_path, "a", encoding="utf-8") as f:
        f.write('"""' + title + "\n")
        for i, q in enumerate(questions):
            result = (
                generate_answer(q, data_store)
                .replace("\n", " ")
                .replace("\xa0", " ")
                .replace("□", "-")
                .replace("ㅇ", "-")
                .replace("·", "-")
                .strip()
            )
            result = remove_special_chars_with_space(result)
            f.write(result + "\n")
        f.write('"""' + "\n")


# ✅ 전체 정책 페이지 순회
def crawl_all_policy_pages():
    all_policies = []
    page = 1
    while True:
        list_url = f"https://youth.seoul.go.kr/infoData/plcyInfo/ctList.do?sprtInfoId=&plcyBizId=&key=2309150002&sc_detailAt=&pageIndex={page}&orderBy=regYmd+desc&blueWorksYn=N&tabKind=002&sw=&sc_rcritCurentSitu=001&sc_rcritCurentSitu=002"
        page_policies = crawl_policy_list(list_url)
        if not page_policies:
            print("❌ 더 이상 데이터가 없습니다. 종료.")
            break
        all_policies.extend(page_policies)
        page += 1
    print(f"\n✅ 총 수집된 정책 수: {len(all_policies)}개")
    return all_policies


# ✅ 실행
if __name__ == "__main__":

    file1_path = "D:/dochoi/workspace/PythonProject1/my_data_directory/your_data_file1.txt"
    file3_path = "D:/dochoi/workspace/PythonProject1/my_data_directory/your_data_file3.txt"

    saved_policy_ids = load_saved_policy_ids_from_files(file1_path, file3_path)
    all_policies = crawl_all_policy_pages()

    test_questions = [
        "사업개요에 대해 알려줘",
        "신청자격은 어떻게 되나요?",
        "신청방법이 궁금해요",
        "기타 정보가 있나요?",
        "지원 내용이 뭔가요?"
    ]

    dsn = cx_Oracle.makedsn("192.168.0.231", 1521, service_name="helperpdb")
    conn = cx_Oracle.connect(user="helper", password="1111", dsn=dsn)
    cursor = conn.cursor()

    inserted_count = 0

    for i, policy in enumerate(all_policies):
        policy_id = policy["policy_id"]
        if not policy_id:
            continue

        if policy_id in saved_policy_ids:
            print(f"[중복 - ID 기준] '{policy_id}' 이미 저장되어 건너뜀")
            continue

        detail_url = f"https://youth.seoul.go.kr/infoData/plcyInfo/view.do?plcyBizId={policy_id}&tab=001&key=2309150002"

        try:
            res = requests.get(detail_url)
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, "html.parser")
            policy_title = soup.find("strong", class_="title").get_text(strip=True)

            data_store = crawl_all_sections(detail_url)

            with open(file1_path, "a", encoding="utf-8") as f:
                f.write(f"{policy_title}\n{detail_url}\n\n")

            # ✅ DB INSERT (중복 무시)
            try:
                cursor.execute("""
                    INSERT INTO policies (title, url) VALUES (:1, :2)
                """, (policy_title, detail_url))
                inserted_count += 1
                print(f"[INSERT 완료] {policy_title}")
            except cx_Oracle.IntegrityError:
                print(f"[중복 - DB 기준] {policy_title} 이미 존재하여 건너뜀")
            except Exception as e:
                print(f"[DB ERROR] 제목 :  {policy_title} | 오류 : {e}")

            save_policy_result_to_file(file3_path, policy_title, test_questions, data_store)
            saved_policy_ids.add(policy_id)

        except Exception as e:
            print(f"[{i+1}] 정책 처리 중 오류 - ID: {policy_id} / 오류: {e}")
            continue

    conn.commit()
    cursor.close()
    conn.close()

    print(f"\n✅ 수집된 전체 정책 수: {len(all_policies)}개")
    print(f"🟢 DB에 실제 INSERT 된 정책 수: {inserted_count}개")
    print("\n----------------------- 데이터 저장 완료 -----------------------------")
