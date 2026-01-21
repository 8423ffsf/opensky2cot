Meshtastic COT 转发器：通过 MQTT 实现与 Meshtastic 的无缝对接

Meshtastic 节点 COT 转发工具

A tool to forward Meshtastic node data to COT (Cursor on Target) compatible systems via MQTT.

功能介绍

- 从 Meshtastic MQTT 服务器订阅节点数据（位置、硬件信息、遥测数据等）

- 支持 AES-256-CTR 解密加密频道数据

- 转换节点数据为 COT 标准格式（兼容 ATAK、地图可视化工具等）

- 支持 UDP/TCP/广播三种传输协议

- 包含丰富元数据：定位精度、电池状态、信号强度、硬件型号等

- 自动清理过期节点数据，避免冗余

环境要求

- Python 3.7+

- 依赖库：requests、paho-mqtt、pycryptodome、protobuf

- Meshtastic 固件版本 2.0+（推荐 2.5+）

安装步骤

1. 克隆仓库与依赖安装

# 克隆本项目（若为本地文件，跳过此步）
git clone <本项目仓库地址>
cd meshtastic-cot-forwarder

# 安装依赖库
pip install requests paho-mqtt pycryptodome protobuf

2. 编译 Meshtastic Protobuf 文件

需获取 Meshtastic 官方 Protobuf 定义文件并编译为 Python 模块：

# 克隆 Meshtastic Protobuf 仓库
git clone https://github.com/meshtastic/protobufs.git
cd protobufs

# 编译核心 Protobuf 文件（生成 .py 解析文件）
protoc --python_out=../meshtastic-cot-forwarder meshtastic/service.proto \
  meshtastic/mesh.proto \
  meshtastic/nodeinfo.proto \
  meshtastic/telemetry.proto

# 返回工具目录
cd ../meshtastic-cot-forwarder

3. 文件结构确认

确保工具目录下包含以下文件：

meshtastic-cot-forwarder/
├── meshtastic_cot.py        # 主程序
├── meshtastic/              # 编译后的 Protobuf 模块
│   ├── service_pb2.py
│   ├── mesh_pb2.py
│   ├── nodeinfo_pb2.py
│   └── telemetry_pb2.py
└── README.md                # 本说明文档

配置与使用

核心配置参数

参数名

说明

默认值

MQTT_BROKER

Meshtastic MQTT 服务器地址

mqtt.meshtastic.org

MQTT_TOPIC

订阅的 MQTT 主题

msh/#

MESHTASTIC_PSK

频道 PSK 密钥（Base64 格式）

AQ==（默认频道密钥）

COT_TYPE

COT 事件类型（目标分类）

a-f-G-U-C

命令行参数说明

--proto        传输协议：tcp/udp/broadcast（默认：broadcast）
--addr         目标地址（默认：广播为 239.2.3.1，UDP/TCP 为 127.0.0.1）
--port         目标端口（默认：广播 6969，UDP 8999，TCP 8099）
--interval     发送间隔（秒，默认：10）
--debug        调试模式（打印 COT 原始数据，默认：关闭）
--mqtt-broker  自定义 MQTT 服务器地址
--mqtt-topic   自定义 MQTT 订阅主题
--psk          频道 PSK 密钥（Base64 格式）
--cot-type     COT 事件类型（如 a-f-G-U-C、a-f-M-F-C）

常用运行示例

示例 1：默认配置（广播发送，默认频道）

python meshtastic_cot.py

示例 2：自定义 PSK 密钥 + UDP 发送

python meshtastic_cot.py --proto udp --addr 192.168.1.100 --port 8999 \
  --psk "你的Base64格式PSK密钥" --interval 5

示例 3：调试模式 + 自定义 COT 类型

python meshtastic_cot.py --debug --cot-type "a-f-M-F-C" \
  --mqtt-broker "mqtt.example.com" --mqtt-topic "msh/cn/2/json/#"

示例 4：TCP 发送到 ATAK 服务器

python meshtastic_cot.py --proto tcp --addr 192.168.1.200 --port 8087 \
  --interval 8 --psk "你的PSK密钥"

COT 事件类型说明

COT 类型

含义

适用场景

a-f-G-U-C

友好、地面、未知、通信节点

普通地面 Meshtastic 节点

a-f-G-F-C

友好、地面、友军、通信节点

已知己方地面节点

a-f-M-U-C

友好、移动、未知、通信节点

移动中的地面节点

a-n-G-U-C

中立、地面、未知、通信节点

公开共享节点

a-f-A-U-C

友好、空中、未知、通信节点

无人机搭载的节点

元数据说明

COT 格式中新增 <meshtastic_meta> 节点，包含以下元数据：

字段名

单位

说明

hw_model

-

硬件型号（如 ESP32_C3、TTGO_T_BEAM）

hw_version

-

硬件版本（如 v1.2）

firmware_version

-

固件版本（如 2.5.1）

long_name

-

节点长名称（如 Outdoor-Mesh-Node-01）

battery_voltage

V

电池电压（如 3.9V）

battery_level

%

电池电量百分比（0~100%）

rssi

dBm

信号接收强度（负值，越接近 0 越好）

snr

dB

信噪比（正值，越大抗干扰能力越强）

air_utilization

%

空中信道利用率（反映网络拥堵程度）

常见问题

1. 解密失败

- 检查 PSK 密钥是否与节点频道一致（从 Meshtastic App 导出 Base64 格式密钥）

- 确认频道是否加密（未加密频道无需填写 PSK，或保持默认 AQ==）

2. 无节点数据

- 确认 MQTT 服务器地址和主题正确

- 节点需开启 MQTT 上报功能（App → 设置 → MQTT）

- 等待节点周期性上报（位置/元数据上报间隔可能为几分钟）

3. 接收端无法识别

- 确认 COT 类型是否适配接收端（推荐先使用默认 a-f-G-U-C）

- 检查传输协议和端口是否与接收端一致（如 ATAK 默认 TCP 8087）

4. Protobuf 相关报错

- 确认 Protobuf 文件已正确编译

- 检查 Protobuf 库版本是否兼容（推荐 3.20+）

优化建议

1. 高频发送场景：将 TCP 改为长连接（当前为短连接）

2. 大规模节点：增加节点数据分页发送，避免网络拥堵

3. 自定义接收端：扩展 <meshtastic_meta> 节点，添加专属元数据

4. 稳定性提升：添加 MQTT 自动重连机制、日志保存功能

许可证

MIT License

免责声明

本工具为第三方开发，与 Meshtastic 官方无关联。使用时请遵守 Meshtastic 相关协议和当地法律法规，请勿用于非法用途。
