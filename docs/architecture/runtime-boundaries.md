# 运行边界

- Django/PostgreSQL 是业务状态的唯一写入来源。
- React 只通过 Django API 访问后端。
- Workers 通过 Celery queues 执行异步工作。
- Storage Provider 是唯一文件访问边界。
- Markdown 文件是生成快照，不是业务状态源。
- 外部系统只作为单向导出目标。
- 只有 Nginx 暴露主机端口；具体端口由部署环境配置维护。
- Docker Compose 网络必须显式使用 `10.89.0.0/24` IPAM 子网。Docker 不能在这台实验室公网入口服务器上自动选择 bridge 子网。
- 到实验室客户端网段的路由绝不能解析到 `dev br-*` 或 `docker0`。
