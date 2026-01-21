#!/bin/bash
INTERVAL=10
PY_FILE="meshtastic_cot.py"

# 停止进程的函数（Ctrl+C触发）
stop_all() {
    echo -e "\n正在停止所有模式..."
    kill $BROADCAST_PID >/dev/null 2>&1
    kill $TCP_PID >/dev/null 2>&1
    echo "双模式已全部停止"
    exit 0
}

# 捕获Ctrl+C，执行停止函数
trap stop_all SIGINT

echo -e "======================================"
echo -e " 双模式同步运行中（均每${INTERVAL}s发送一次）"
echo -e " ✅ 广播模式：后台运行"
echo -e " ✅ TCP模式：后台运行（日志可查看）"
echo -e "======================================"
echo -e " 按 Ctrl+C 一键停止所有进程"
echo -e "======================================\n"

# 启动广播模式（后台运行，记录PID）
python3 $PY_FILE --proto broadcast --interval $INTERVAL > broadcast.log 2>&1 &
BROADCAST_PID=$!
echo "广播模式已启动，进程ID：$BROADCAST_PID，日志：broadcast.log"

# 启动TCP模式（后台运行，记录PID，日志留存）
python3 $PY_FILE --proto tcp --interval $INTERVAL > tcp.log 2>&1 &
TCP_PID=$!
echo "TCP模式已启动，进程ID：$TCP_PID，日志：tcp.log"
echo -e "\n双模式启动完成 ✅\n"

# 保持脚本运行，等待Ctrl+C
while true; do
    sleep 1
done