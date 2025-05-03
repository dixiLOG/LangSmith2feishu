# LangSmith2Bitable

LangSmith2Bitable 是一个自动化工具，用于将 LangSmith 平台的 LLM 对话数据同步到飞书多维表格(Bitable)，支持增量同步和自动清理过期数据。

## 功能特点

- **增量同步**：只拉取上次同步后的新记录，避免重复处理
- **用户消息提取**：自动从对话中提取最后一条用户输入
- **本地记录管理**：使用本地JSON文件存储同步状态和记录信息
- **自动去重**：基于run_id检测并避免重复同步相同记录
- **过期数据清理**：根据配置的保留天数自动清理过期数据
- **完善的错误处理**：对API错误和数据解析异常进行妥善处理
- **详细的日志输出**：提供清晰的执行状态和结果反馈

## 安装要求

1. Python 3.6+
2. 依赖包：
   ```
   pip install langsmith requests python-dotenv ipykernel
   ```

## 配置说明

在运行前需要配置以下参数：

```python
# LangSmith配置
LS_API_KEY = "你的LangSmith API密钥"
LS_PROJECT = "你的LangSmith项目名称"

# 飞书多维表格配置
APP_ID = "飞书应用ID"
APP_SECRET = "飞书应用密钥"
BASE_ID = "多维表格Base ID"
TABLE_ID = "多维表格Table ID"

# 本地存储配置
STATE_FILE = "state.json"  # 同步状态文件
LOCAL_RECORDS_FILE = "local_records.json"  # 本地记录缓存

# 数据保留配置
RETENTION_DAYS = 14  # 数据保留天数，超过将被清理
```

## 使用方法

### 初次设置

1. 确保已安装所有依赖
2. 配置LangSmith和飞书相关参数
3. 确保脚本有权限创建和修改本地JSON文件

### 运行方式

1. 直接运行脚本：
   ```
   python sync_langsmith_to_bitable.py
   ```

2. 设置为定时任务（推荐，以Linux crontab为例）：
   ```
   # 每小时运行一次
   0 * * * * /usr/bin/python /path/to/sync_langsmith_to_bitable.py
   ```

## 项目结构

- `sync_langsmith_to_bitable.py`：主程序文件
- `state.json`：记录上次同步时间
- `local_records.json`：存储已同步的记录信息

## 数据同步流程

1. 加载上次同步状态
2. 清理过期记录（基于本地记录）
3. 从LangSmith拉取新的对话数据
4. 提取有效用户消息
5. 写入飞书多维表格
6. 更新本地同步状态和记录

## 注意事项

- 首次运行会同步所有历史记录
- 如需从头开始同步，删除`state.json`和`local_records.json`文件
- 建议先设置较长的`RETENTION_DAYS`值，确认数据正确后再调整
- 修改配置参数后需要重启程序

## 关于飞书表格结构

该程序假设飞书多维表格中存在以下字段：
- `run_id`：LangSmith运行ID
- `timestamp`：时间戳
- `input`：用户输入内容



## GitHub Actions 自动化部署

该项目支持使用GitHub Actions自动化定时执行同步任务。配置已经包含在`.github/workflows/sync_schedule.yml`文件中，按照以下时间表执行：

- **工作时间（北京时间9:00-18:00，周一至周五）**: 每30分钟执行一次
- **非工作时间（包括夜间和周末）**: 每2小时执行一次

### 部署步骤

1. **将代码推送到GitHub仓库**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/你的用户名/LangSmith2Bitable.git
   git push -u origin master  # 或 main，取决于你的默认分支
   ```

2. **设置GitHub Secrets**
   
   在GitHub仓库页面，点击 Settings → Secrets and variables → Actions → New repository secret，添加以下三个密钥：
   
   - `LS_API_KEY`: LangSmith API密钥
   - `APP_ID`: 飞书应用ID
   - `APP_SECRET`: 飞书应用密钥
   
3. **启用GitHub Actions**
   
   在GitHub仓库页面，点击Actions标签，根据提示启用工作流。工作流将按照预设的时间表自动运行。

4. **手动触发**
   
   如需手动触发同步，可在Actions标签下选择"LangSmith2Bitable Sync"工作流，点击"Run workflow"按钮。

### 注意事项

- GitHub Actions运行时会使用仓库中的状态文件(`state.json`和`local_records.json`)，确保这些文件已添加到仓库并有正确的权限。
- 如需更改同步频率，可修改`.github/workflows/sync_schedule.yml`文件中的cron表达式。
- GitHub Actions在每次运行后会提交更新后的状态文件，以便下次从正确的时间点继续同步。

### GitHub Actions限制说明

GitHub Actions对免费账户和组织有以下主要限制：

1. **计算时间**：
   - 公共仓库：每月2,000分钟的免费额度
   - 私有仓库：每月2,000分钟（个人账户）/3,000分钟（组织免费计划）

2. **并发任务**：最多20个并发任务

3. **存储限制**：GitHub Actions制品存储为500MB

4. **任务超时**：每个任务最长运行时间为6小时

5. **API请求限制**：每小时约1,000个API请求

6. **定时任务限制**：
   - 最短间隔为5分钟
   - 定时任务可能有最多15分钟的延迟

本项目的半小时一次和两小时一次的同步任务设置在免费计划的限制范围内。如果脚本每次运行仅需几分钟，那么每月的免费额度通常足够使用。

可以在GitHub仓库的"Settings → Actions → General"页面查看您的使用情况。

### 优化GitHub Actions使用

为了最大化免费额度的使用效率，以下是一些优化建议：

1. **减少运行频率**：根据实际需求调整cron表达式，避免不必要的频繁运行

2. **优化脚本效率**：
   - 确保脚本执行时间尽可能短
   - 仅处理必要的数据，避免大量不必要的API调用

3. **使用缓存**：
   - 在workflow中添加缓存步骤，避免重复安装依赖
   ```yaml
   - uses: actions/cache@v3
     with:
       path: ~/.cache/pip
       key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements.txt') }}
   ```

4. **设置条件触发**：
   - 使用条件表达式，仅在特定情况下运行workflow的某些步骤

5. **监控使用情况**：定期检查Actions的使用量，及时调整策略

## 故障排除

### 脚本运行问题

如果同步过程中遇到问题，请检查：

1. **API凭证是否正确**：确认LangSmith和飞书的API密钥是否有效
2. **网络连接**：检查与LangSmith和飞书API的网络连接是否正常
3. **权限问题**：确保脚本有权限读写本地文件
4. **数据格式**：检查记录格式是否符合预期

### GitHub Actions相关问题

1. **工作流未触发**：
   - 检查cron表达式是否正确配置
   - 确认工作流文件`.github/workflows/sync_schedule.yml`语法正确
   - 查看Actions选项卡中是否有错误日志

2. **Secrets配置问题**：
   - 确保所有必需的Secrets (`LS_API_KEY`, `APP_ID`, `APP_SECRET`) 已正确配置
   - Secrets值不能包含引号或特殊格式

3. **权限错误**：
   - 如果出现"refusing to allow a GitHub App to create or update workflow"错误，需要检查仓库权限设置
   - 在仓库的Settings → Actions → General → Workflow permissions中设置为"Read and write permissions"

4. **运行超时**：
   - 如果任务经常超时，考虑优化脚本性能或减少处理的数据量

5. **配额用尽**：
   - 如果达到了GitHub Actions的免费配额限制，可以等待下个月额度重置或升级到付费计划

如需进一步的帮助，请查看[GitHub Actions文档](https://docs.github.com/en/actions)。

## 许可证

MIT License