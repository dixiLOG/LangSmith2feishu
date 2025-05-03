import os
import json
import time
from datetime import datetime, timedelta
import requests
from langsmith import Client
import sys

# 设置控制台输出编码为UTF-8，解决中文乱码问题
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    os.system('chcp 65001')  # 设置命令行代码页为UTF-8

"""
sync_langsmith_to_bitable.py

功能：定时从 LangSmith 平台拉取新的 LLM 对话（仅提取用户输入的最后一条消息），
     同步保存到飞书多维表格（Bitable）中，并基于本地记录自动清理过期数据。

主要特点：
1. 增量同步 - 只拉取上次同步后的新记录
2. 本地记录管理 - 使用本地JSON文件存储同步状态和记录
3. 自动去重 - 避免重复同步相同记录 
4. 自动清理 - 根据配置的保留天数清理过期数据
5. 容错处理 - 对API错误和解析错误进行适当处理

使用前准备：
 1. pip install langsmith requests
 2. 配置以下参数：
    - LS_API_KEY - LangSmith 的 API Key
    - APP_ID - 飞书自建应用的 App ID
    - APP_SECRET - 飞书自建应用的 App Secret
    - LS_PROJECT - LangSmith 项目名称
    - BASE_ID, TABLE_ID - 飞书多维表格信息
    - RETENTION_DAYS - 数据保留天数
 3. 确保脚本有可写权限目录，用于保存 state.json 和 local_records.json。
 
使用方法：
 - 直接运行脚本：python sync_langsmith_to_bitable.py
 - 建议设置为定时任务，如每小时同步一次
 - 也可以通过GitHub Actions自动运行

版本: 1.0.0
"""

# ========== 配置区 ==========
# LangSmith 项目名称
LS_PROJECT = "甬E红芯"

# 飞书多维表格 Base 和 Table ID
BASE_ID  = "PSThb9x5KaN3HtsWVzucNVaQnMp"
TABLE_ID = "tblaWASAqE8wtmpg"

# 本地状态和记录存储文件
STATE_FILE = "state.json"          # 存储上次同步时间
LOCAL_RECORDS_FILE = "local_records.json"  # 存储已同步的记录

# API 凭证 - 优先从环境变量读取，否则使用默认值
LS_API_KEY = os.environ.get("LS_API_KEY", "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")
APP_ID = os.environ.get("APP_ID", "cli_a89e30ce0cf9900b")
APP_SECRET = os.environ.get("APP_SECRET", "Q4sw3MuSq8wjqKrG3g3JKdnnnpPaTE53")

# 数据保留天数，超过这个天数的记录将被删除
# 设为0将删除所有记录，设为负数将不删除任何记录
RETENTION_DAYS = 14
# =============================

def load_state():
    """
    从本地读取上次同步状态，包括 last_time。
    
    返回:
        dict: 包含上次同步时间的字典，格式为 {"last_time": "ISO时间字符串"}
              如果文件不存在，返回一个设置很早时间的默认值
    """
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    # 初始时间设很早，确保首次运行时拉取所有记录
    return {"last_time": "1970-01-01T00:00:00Z"}

def save_state(state: dict):
    """
    将当前同步状态写入本地文件。
    
    参数:
        state (dict): 包含同步状态信息的字典，如 {"last_time": "2023-01-01T00:00:00Z"}
    """
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def load_local_records():
    """
    加载本地缓存的记录列表。
    
    返回:
        list: 包含所有已同步记录的列表，如果文件不存在返回空列表
    """
    if os.path.exists(LOCAL_RECORDS_FILE):
        with open(LOCAL_RECORDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_local_records(records):
    """
    将记录列表保存到本地缓存文件。
    
    参数:
        records (list): 要保存的记录列表
    """
    with open(LOCAL_RECORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

def get_tenant_token() -> str:
    """
    获取飞书应用的tenant_access_token。
    
    返回:
        str: 获取到的token字符串
        
    异常:
        Exception: 当API请求失败或返回非0状态码时抛出
    """
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": APP_ID, "app_secret": APP_SECRET}
    
    print(f"[INFO] 请求获取飞书token，使用APP_ID: {APP_ID}, APP_SECRET: {APP_SECRET[:5]}***")
    
    resp = requests.post(url, json=payload)
    data = resp.json()
    
    if data.get("code") != 0:
        print(f"[ERROR] 获取token失败: {data}")
        raise Exception(f"获取token失败: {data}")
    
    token = data["tenant_access_token"]
    print(f"[SUCCESS] 获取到飞书token: {token[:10]}...")
    return token

def fetch_new_runs(client, last_time):
    """
    从LangSmith拉取最新的对话记录，提取用户消息。
    
    参数:
        client (Client): LangSmith客户端实例
        last_time (str): ISO格式的时间字符串，仅拉取此时间之后的记录
        
    返回:
        list: 处理后的运行记录列表，每条记录都包含提取的用户输入
    """
    import copy
    
    print(f"[INFO] 正在拉取 {last_time} 之后的新记录...")
    
    # 构造过滤条件：name=message 且 start_time > last_time
    filter_str = f'and(eq(name, "message"), gt(start_time, "{last_time}"))'
    # client.list_runs返回一个生成器，转换为列表以便多次遍历
    runs_list = list(client.list_runs(
        project_name=LS_PROJECT,
        filter=filter_str,
    ))
    
    processed_runs = []
    
    # 遍历每个运行记录，提取用户消息
    for run in runs_list:
        if hasattr(run, 'inputs') and isinstance(run.inputs, dict) and 'messages' in run.inputs:
            messages = run.inputs['messages']
            
            # 查找最后一个用户消息
            last_user_content = None
            for msg in reversed(messages):
                if msg.get('role') == 'user' and 'content' in msg:
                    last_user_content = msg['content']
                    break
            
            # 如果找到用户消息，创建简化的运行对象
            if last_user_content:
                processed_run = copy.deepcopy(run)
                processed_run.inputs = {"input": last_user_content}
                processed_runs.append(processed_run)
    
    print(f"[INFO] 从LangSmith获取到 {len(runs_list)} 条记录，提取出 {len(processed_runs)} 条有效用户消息")
    return processed_runs

def build_records(runs):
    """
    根据处理后的运行记录构建用于写入飞书的记录列表。
    
    参数:
        runs (list): 处理后的LangSmith运行记录列表
        
    返回:
        tuple: (records, newest_time)
            - records: 构建好的记录列表，每条包含run_id、timestamp和input字段
            - newest_time: 所有记录中的最新时间，用于更新同步状态
    """
    records = []
    newest_time = None

    for run in runs:
        # 提取用户输入文本
        input_text = run.inputs.get("input", "").strip()
        ts = run.start_time

        # 跳过空输入
        if not input_text:
            continue

        # 确保run_id为字符串类型
        run_id = str(run.id)
        
        # 确保时间戳为ISO格式字符串
        if hasattr(ts, 'isoformat'):
            ts = ts.isoformat()
        else:
            ts = str(ts)

        # 构建记录对象，包含飞书字段和本地管理字段
        records.append({
            "fields": {
                "run_id": run_id,
                "timestamp": ts,
                "input": input_text
            },
            "run_id": run_id,  # 在本地记录中额外保存run_id方便查询
            "timestamp": ts,   # 在本地记录中额外保存timestamp方便筛选
            "record_id": None  # 创建后会被更新为飞书返回的record_id
        })
        
        # 更新最新时间
        if newest_time is None or run.start_time > newest_time:
            newest_time = run.start_time

    return records, newest_time

def push_to_bitable(token: str, records: list):
    """
    将记录列表推送到飞书多维表格，并更新本地记录。
    
    参数:
        token (str): 飞书租户访问令牌
        records (list): 要推送的记录列表
        
    返回:
        dict: API响应结果
        
    特性:
        - 自动过滤已存在的记录，避免重复写入
        - 将新创建记录的record_id保存到本地缓存
    """
    if not records:
        print("[INFO] 没有记录需要推送")
        return {}
        
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BASE_ID}/tables/{TABLE_ID}/records/batch_create"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    
    # 检查是否有重复的run_id
    local_records = load_local_records()
    existing_run_ids = {r.get("run_id") for r in local_records}
    
    # 过滤掉已经存在的记录
    unique_records = [r for r in records if r.get("run_id") not in existing_run_ids]
    
    if not unique_records:
        print("[INFO] 所有记录已存在于本地缓存，无需重复写入")
        return {}
    
    print(f"[INFO] 准备写入 {len(unique_records)} 条新记录（过滤掉 {len(records) - len(unique_records)} 条重复记录）")
    
    # 仅发送fields部分
    api_records = [{"fields": record["fields"]} for record in unique_records]
    
    payload = {"records": api_records}
    resp = requests.post(url, headers=headers, json=payload)
    
    if resp.status_code != 200:
        print(f"[ERROR] 写入飞书失败，状态码: {resp.status_code}")
        print(f"[ERROR] 响应内容: {resp.text}")
        resp.raise_for_status()
    
    result = resp.json()
    
    # 更新本地记录中的record_id
    if "data" in result and "records" in result["data"]:
        for i, record_info in enumerate(result["data"]["records"]):
            if i < len(unique_records):
                unique_records[i]["record_id"] = record_info["record_id"]
    
    # 只添加新记录到本地缓存
    local_records.extend(unique_records)
    save_local_records(local_records)
    print(f"[SUCCESS] 成功写入 {len(unique_records)} 条记录到飞书，并更新本地缓存")
    
    return result

def find_expired_records(days=RETENTION_DAYS):
    """
    从本地缓存中查找过期记录。
    
    参数:
        days (int): 数据保留天数，超过这个天数的记录将被认为过期
        
    返回:
        list: 过期记录列表
        
    特性:
        - 当days <= 0时返回所有记录
        - 使用ISO格式时间戳进行比较
        - 优雅处理解析错误
    """
    if days <= 0:
        print(f"[INFO] 保留天数设为 {days}，将返回所有记录")
        return load_local_records()
    
    local_records = load_local_records()
    cutoff_date = datetime.now() - timedelta(days=days)
    expired_records = []
    
    print(f"[INFO] 正在查找早于 {cutoff_date.isoformat()} 的过期记录...")
    
    for record in local_records:
        try:
            ts = record.get("timestamp", "")
            if ts:
                # 解析ISO时间戳，移除可能的时区信息以简化处理
                if "+" in ts:
                    ts = ts.split("+")[0]
                record_time = datetime.fromisoformat(ts)
                
                if record_time < cutoff_date:
                    expired_records.append(record)
        except Exception as e:
            print(f"[WARN] 解析记录时间失败: {e}, 记录时间戳: {ts}")
    
    print(f"[INFO] 本地找到 {len(expired_records)} 条超过 {days} 天的记录")
    return expired_records

def delete_records_from_bitable(token: str, records):
    """
    从飞书多维表格中删除指定记录，同时更新本地缓存。
    
    参数:
        token (str): 飞书租户访问令牌
        records (list): 要删除的记录列表
        
    返回:
        int: 成功删除的记录数量
        
    特性:
        - 自动过滤无效记录（缺少record_id的记录）
        - 分批删除，避免超出API限制
        - 同步更新本地缓存
    """
    if not records:
        print("[INFO] 没有需要删除的记录")
        return 0
    
    # 过滤出有record_id的记录
    valid_records = [r for r in records if r.get("record_id")]
    
    if not valid_records:
        print("[WARN] 没有有效的record_id，无法删除")
        return 0
    
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BASE_ID}/tables/{TABLE_ID}/records/batch_delete"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    
    record_ids = [record["record_id"] for record in valid_records]
    
    # 批量删除，每次最多删除500条（API限制）
    batch_size = 500
    deleted_count = 0
    
    for i in range(0, len(record_ids), batch_size):
        batch_ids = record_ids[i:i+batch_size]
        payload = {"records": batch_ids}
        
        print(f"[INFO] 正在删除第 {i+1} 到 {i+len(batch_ids)} 条记录...")
        
        resp = requests.post(url, headers=headers, json=payload)
        
        if resp.status_code != 200:
            print(f"[ERROR] 删除记录失败，状态码: {resp.status_code}")
            print(f"[ERROR] 响应内容: {resp.text}")
        else:
            deleted_count += len(batch_ids)
            print(f"[SUCCESS] 成功删除 {len(batch_ids)} 条记录")
    
    # 从本地缓存中删除这些记录
    if deleted_count > 0:
        local_records = load_local_records()
        deleted_ids = set(record_ids)
        updated_records = [r for r in local_records if r.get("record_id") not in deleted_ids]
        save_local_records(updated_records)
        print(f"[INFO] 从本地缓存中删除了 {len(local_records) - len(updated_records)} 条记录")
    
    return deleted_count

def main():
    """
    主函数，协调整个同步流程。
    
    流程:
        1. 检查配置和环境
        2. 加载上次同步状态
        3. 清理过期记录
        4. 拉取新记录
        5. 写入飞书表格
        6. 更新同步状态
    """
    # 检查API密钥配置
    if not LS_API_KEY or not APP_ID or not APP_SECRET:
        print("[ERROR] 缺少API密钥配置，请检查 LS_API_KEY、APP_ID 和 APP_SECRET")
        return

    # 1. 加载上次同步状态
    state = load_state()
    last_time = state["last_time"]
    print(f"[INFO] [{datetime.utcnow().isoformat()}] 上次同步时间: {last_time}")

    # 2. 初始化 LangSmith 客户端
    client = Client(api_key=LS_API_KEY)

    # 3. 获取飞书访问令牌
    token = get_tenant_token()

    # 4. 清理过期记录
    try:
        print(f"[INFO] 开始清理超过 {RETENTION_DAYS} 天的记录...")
        expired_records = find_expired_records(RETENTION_DAYS)
        if expired_records:
            delete_records_from_bitable(token, expired_records)
        else:
            print("[INFO] 没有需要清理的过期记录")
    except Exception as e:
        print(f"[ERROR] 清理过期记录失败: {e}")
        # 不抛出异常，继续执行后续步骤

    # 5. 拉取新记录
    runs = fetch_new_runs(client, last_time)
    if not runs:
        print("[INFO] 无新记录，同步结束")
        return

    # 6. 构建待写入记录列表
    records, newest_time = build_records(runs)
    if not records:
        print("[INFO] 无有效用户输入，同步结束")
        return
    
    print(f"[INFO] 成功构建 {len(records)} 条有效记录")

    # 7. 写入飞书表格
    try:
        push_to_bitable(token, records)
    except Exception as e:
        print(f"[ERROR] 写入飞书多维表格失败: {e}")
        raise

    # 8. 更新同步状态
    state["last_time"] = newest_time.isoformat() if hasattr(newest_time, "isoformat") else str(newest_time)
    save_state(state)
    print(f"[INFO] 已更新同步时间为 {state['last_time']}，下次将只拉取更晚的记录")
    print("[SUCCESS] 同步完成!")

if __name__ == "__main__":
    main()