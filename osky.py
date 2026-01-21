#!/usr/bin/env python3
import requests
import sys
import time
import socket
import xml.etree.ElementTree as ET
import argparse
import paho.mqtt.client as mqtt
import base64
from Crypto.Cipher import AES
from Crypto.Util import Counter
import meshtastic.service_pb2 as service_pb2
import meshtastic.mesh_pb2 as mesh_pb2

# 配置参数（需根据你的 Meshtastic 环境修改）
MQTT_BROKER = "mqtt.meshtastic.org"  # MQTT 服务器地址（官方/自定义）
MQTT_TOPIC = "msh/#"                 # 订阅的 MQTT 主题
MESHTASTIC_PSK = "AQ=="              # 频道 PSK 密钥（Base64 格式，需与节点频道一致）
TIME_FORMAT = '%Y-%m-%dT%H:%M:%SZ'
NODE_CACHE = {}  # 缓存节点数据，避免重复发送

# AES-256-CTR 解密函数（适配 Meshtastic 频道加密）
def decrypt_meshtastic_payload(encrypted_payload, nonce, psk_base64):
    psk = base64.b64decode(psk_base64)
    if len(psk) != 32:
        print("错误：PSK 密钥解码后必须为 32 字节")
        return None
    ctr = Counter.new(128, initial_value=int.from_bytes(nonce, byteorder="big"))
    cipher = AES.new(psk, AES.MODE_CTR, counter=ctr)
    try:
        return cipher.decrypt(encrypted_payload)
    except Exception as e:
        print(f"解密失败：{e}")
        return None

# 解析节点元数据（从 NODEINFO/TELEMETRY 数据包中提取）
def parse_node_metadata(parsed_packet, node_id):
    metadata = {}
    # 解析 NODEINFO_APP 数据包（硬件型号、固件版本等）
    if parsed_packet.decoded.payloadVariant == meshtastic.mesh_pb2.Decoded.PayloadVariant.NODEINFO_APP:
        node_info = parsed_packet.decoded.nodeInfo
        metadata['hw_model'] = node_info.hwModel or "Unknown"  # 硬件型号（如 ESP32-C3、TTGO T-Beam）
        metadata['firmware_version'] = node_info.firmwareVersion or "Unknown"  # 固件版本
        metadata['long_name'] = node_info.longName or ""  # 节点长名称
        metadata['hw_version'] = node_info.hwVersion or "Unknown"  # 硬件版本
        # 更新缓存中的元数据
        if node_id in NODE_CACHE:
            NODE_CACHE[node_id].update(metadata)
        else:
            NODE_CACHE[node_id] = {**metadata, "last_update": time.time()}
    # 解析 TELEMETRY_APP 数据包（电池、信号强度等）
    elif parsed_packet.decoded.payloadVariant == meshtastic.mesh_pb2.Decoded.PayloadVariant.TELEMETRY_APP:
        telemetry = parsed_packet.decoded.telemetry
        metadata['battery_voltage'] = telemetry.batteryVoltage / 1000.0 if telemetry.batteryVoltage else None  # 电池电压（V）
        metadata['battery_level'] = telemetry.batteryLevel if telemetry.batteryLevel != 255 else None  # 电池电量（%，255 为无效值）
        metadata['rssi'] = telemetry.rssi if telemetry.rssi != 0 else None  # 信号强度（dBm）
        metadata['snr'] = telemetry.snr if telemetry.snr != 0 else None  # 信噪比（dB）
        metadata['air_utilization'] = telemetry.airUtilTx if telemetry.airUtilTx else None  # 空中信道利用率（%）
        # 更新缓存中的元数据
        if node_id in NODE_CACHE:
            NODE_CACHE[node_id].update(metadata)
            NODE_CACHE[node_id]['last_update'] = time.time()
    return metadata

# MQTT 消息回调函数（接收并解析 Meshtastic 数据）
def on_mqtt_message(client, userdata, msg):
    try:
        # 解析 ServiceEnvelope 数据包
        service_envelope = service_pb2.ServiceEnvelope()
        service_envelope.ParseFromString(msg.payload)
        if not service_envelope.HasField("meshPacket"):
            return
        
        mesh_packet = service_envelope.meshPacket
        node_id = mesh_packet.fromRadio  # 节点 ID（从数据包中提取）
        if not node_id:
            return
        
        # 解密 payload（仅处理加密数据包）
        if mesh_packet.encrypted and mesh_packet.HasField("payload") and mesh_packet.HasField("nonce"):
            decrypted_payload = decrypt_meshtastic_payload(
                mesh_packet.payload, mesh_packet.nonce, MESHTASTIC_PSK
            )
            if not decrypted_payload:
                return
        else:
            decrypted_payload = mesh_packet.payload
        
        # 解析解密后的 MeshPacket
        parsed_packet = meshtastic.mesh_pb2.MeshPacket()
        parsed_packet.ParseFromString(decrypted_payload)
        
        # 解析元数据（NODEINFO/TELEMETRY）
        parse_node_metadata(parsed_packet, node_id)
        
        # 仅处理位置数据包（POSITION_APP）- 更新位置相关数据
        if parsed_packet.decoded.payloadVariant == meshtastic.mesh_pb2.Decoded.PayloadVariant.POSITION_APP:
            position_data = parsed_packet.decoded.position
            short_name = parsed_packet.decoded.shortName or f"Node-{node_id[:6]}"  # 节点短名称
            
            # 提取核心位置数据
            lat = position_data.latitude
            lon = position_data.longitude
            if lat == 0 and lon == 0:  # 过滤无效位置
                return
            
            # 海拔（优先用几何海拔，无则默认 0）
            hae = position_data.altitude or 0.0
            # 速度（单位：m/s，无则默认 0）
            speed = position_data.speed or 0.0
            # 航向（无则默认 0）
            course = position_data.course or 0.0
            # 定位精度范围（优先用 precision，无则用 hdop 估算）
            if position_data.precision != 0:
                ce = position_data.precision  # 水平精度（米）
            elif position_data.hdop != 0:
                ce = position_data.hdop * 10  # HDOP 估算（10×HDOP 米）
            else:
                ce = 100.0  # 默认精度（100 米）
            le = ce * 2  # 垂直精度（简化为水平精度的 2 倍）
            
            # 构建节点完整数据（合并缓存中的元数据）
            node_data = NODE_CACHE.get(node_id, {})
            node_data.update({
                "short_name": short_name,
                "lat": lat,
                "lon": lon,
                "hae": hae,
                "speed": speed,
                "course": course,
                "ce": ce,
                "le": le,
                "last_update": time.time()
            })
            # 更新缓存
            NODE_CACHE[node_id] = node_data
    except Exception as e:
        print(f"解析 Meshtastic 数据失败：{e}")

# 连接 MQTT 服务器
def connect_mqtt():
    client = mqtt.Client()
    client.on_message = on_mqtt_message
    try:
        client.connect(MQTT_BROKER, 1883, 60)
        client.subscribe(MQTT_TOPIC)
        print(f"已连接 MQTT 服务器：{MQTT_BROKER}，订阅主题：{MQTT_TOPIC}")
        return client
    except Exception as e:
        print(f"MQTT 连接失败：{e}")
        sys.exit(1)

# Meshtastic 数据转 COT 格式（含多元数据）
def meshtastic2cot(node_data, node_id):
    cot = ET.Element('event')
    cot.set('version', '2.0')
    cot.set('uid', f"meshtastic-{node_id.lower()}")  # 唯一标识（Meshtastic 节点 ID）
    cot.set('type', 'a-f-G-U-C')  # COT 类型（可通过命令行参数修改）
    cot.set('how', 'm-g')  # 定位方式（机器生成）
    # 时间戳（UTC 格式）
    current_time = time.gmtime()
    cot.set('time', time.strftime(TIME_FORMAT, current_time))
    cot.set('start', time.strftime(TIME_FORMAT, current_time))
    cot.set('stale', time.strftime(TIME_FORMAT, time.gmtime(time.time() + 120)))  # 2 分钟过期

    # 定位信息（包含精度范围）
    point = ET.SubElement(cot, 'point')
    point.set('lat', f"{node_data['lat']:.6f}")  # 纬度（保留 6 位小数）
    point.set('lon', f"{node_data['lon']:.6f}")  # 经度（保留 6 位小数）
    point.set('hae', f"{node_data['hae']:.1f}")  # 海拔（米）
    point.set('ce', f"{node_data['ce']:.1f}")    # 水平精度范围（米）
    point.set('le', f"{node_data['le']:.1f}")    # 垂直精度范围（米）

    # 节点详细信息（含多元数据）
    det = ET.SubElement(cot, 'detail')
    # 基础信息
    ET.SubElement(det, 'contact', attrib={'callsign': node_data['short_name']})
    # 扩展元数据节点
    meshtastic_meta = ET.SubElement(det, 'meshtastic_meta')
    # 硬件相关
    ET.SubElement(meshtastic_meta, 'hw_model').text = node_data.get('hw_model', 'Unknown')
    ET.SubElement(meshtastic_meta, 'hw_version').text = node_data.get('hw_version', 'Unknown')
    ET.SubElement(meshtastic_meta, 'firmware_version').text = node_data.get('firmware_version', 'Unknown')
    # 节点名称
    ET.SubElement(meshtastic_meta, 'long_name').text = node_data.get('long_name', '')
    # 电池信息（保留 2 位小数）
    if node_data.get('battery_voltage') is not None:
        ET.SubElement(meshtastic_meta, 'battery_voltage', attrib={'unit': 'V'}).text = f"{node_data['battery_voltage']:.2f}"
    if node_data.get('battery_level') is not None:
        ET.SubElement(meshtastic_meta, 'battery_level', attrib={'unit': '%'}).text = str(node_data['battery_level'])
    # 信号相关（保留 1 位小数）
    if node_data.get('rssi') is not None:
        ET.SubElement(meshtastic_meta, 'rssi', attrib={'unit': 'dBm'}).text = str(node_data['rssi'])
    if node_data.get('snr') is not None:
        ET.SubElement(meshtastic_meta, 'snr', attrib={'unit': 'dB'}).text = f"{node_data['snr']:.1f}"
    # 信道利用率
    if node_data.get('air_utilization') is not None:
        ET.SubElement(meshtastic_meta, 'air_utilization', attrib={'unit': '%'}).text = f"{node_data['air_utilization']:.1f}"

    # 备注信息（整合关键数据，便于快速查看）
    remarks_parts = [
        f"节点 ID：{node_id}",
        f"定位精度：±{node_data['ce']:.0f}米",
        f"速度：{node_data['speed']:.1f}m/s"
    ]
    if node_data.get('battery_level') is not None:
        remarks_parts.append(f"电量：{node_data['battery_level']}%")
    if node_data.get('rssi') is not None:
        remarks_parts.append(f"信号强度：{node_data['rssi']}dBm")
    ET.SubElement(det, 'remarks').text = " | ".join(remarks_parts)

    # 运动轨迹（速度、航向）
    track = ET.SubElement(det, 'track')
    track.set('course', f"{node_data['course']:.1f}")  # 航向（度）
    track.set('speed', f"{node_data['speed']:.1f}")    # 速度（m/s）

    return ET.tostring(cot)

# 数据发送函数（复用原 UDP/TCP/广播逻辑）
def send_broadcast(addr, port, data):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.sendto(data, (addr, port))
    s.close()

def send_udp(addr, port, data):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(data, (addr, port))
    s.close()

def send_tcp(addr, port, data):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((addr, port))
        s.send(data)
        s.close()
    except Exception as e:
        print(f"TCP 发送失败：{e}")

# 主发送逻辑（从缓存中读取节点数据并转发）
def send_meshtastic_cot(args):
    # 选择发送协议
    sender = None
    addr = args.addr
    port = args.port
    if args.proto.lower() == 'udp':
        addr = addr or '127.0.0.1'
        port = port or 8999
        sender = send_udp
    elif args.proto.lower() == 'tcp':
        addr = addr or '127.0.0.1'
        port = port or 8099
        sender = send_tcp
    elif args.proto.lower() == 'broadcast':
        addr = addr or '239.2.3.1'
        port = port or 6969
        sender = send_broadcast
    print(f"通过 {args.proto.upper()} 发送到 {addr}:{port}，COT 类型：{args.cot_type}")

    # 循环发送缓存的节点数据
    while True:
        try:
            # 清理过期节点（超过 2 分钟未更新）
            current_time = time.time()
            expired_nodes = [n for n, d in NODE_CACHE.items() if current_time - d['last_update'] > 120]
            for node_id in expired_nodes:
                del NODE_CACHE[node_id]
                print(f"清理过期节点：{node_id}")
            
            # 发送所有有效节点数据（需包含位置信息）
            valid_nodes = [n for n, d in NODE_CACHE.items() if 'lat' in d and 'lon' in d]
            if valid_nodes:
                print(f"当前有效节点数：{len(valid_nodes)}")
                for node_id in valid_nodes:
                    node_data = NODE_CACHE[node_id]
                    # 替换 COT 类型（从命令行参数传入）
                    cot_data = meshtastic2cot(node_data, node_id).replace(
                        b'a-f-G-U-C', args.cot_type.encode()
                    )
                    if args.debug:
                        print(f"发送节点 {node_id} 的 COT 数据：\n{cot_data.decode('utf-8')}")
                    sender(addr, port, cot_data)
                    time.sleep(0.1)  # 避免发送过快
            else:
                print("暂无有效节点数据（需等待节点上报位置/元数据），等待中...")
            
            time.sleep(args.interval)  # 按间隔重复发送
        except Exception as e:
            print(f"发送失败：{e}")
            time.sleep(1)

if __name__ == '__main__':
    # 解析命令行参数（新增 COT 类型参数）
    parser = argparse.ArgumentParser()
    parser.add_argument("--proto", help="协议：tcp/udp/broadcast", default="broadcast")
    parser.add_argument("--addr", help="目标地址")
    parser.add_argument("--port", help="目标端口", type=int, default=0)
    parser.add_argument("--interval", help="发送间隔（秒）", type=int, default=10)
    parser.add_argument("--debug", help="调试模式（打印 COT 数据）", action="store_true")
    parser.add_argument("--mqtt-broker", help="自定义 MQTT 服务器地址", default=MQTT_BROKER)
    parser.add_argument("--mqtt-topic", help="自定义 MQTT 订阅主题", default=MQTT_TOPIC)
    parser.add_argument("--psk", help="Meshtastic 频道 PSK 密钥（Base64）", default=MESHTASTIC_PSK)
    parser.add_argument("--cot-type", help="COT 事件类型（如 a-f-G-U-C）", default="a-f-G-U-C")
    args = parser.parse_args()

    # 更新配置参数
    MQTT_BROKER = args.mqtt_broker
    MQTT_TOPIC = args.mqtt_topic
    MESHTASTIC_PSK = args.psk

    # 连接 MQTT 并启动消息循环
    mqtt_client = connect_mqtt()
    mqtt_client.loop_start()  # 后台运行 MQTT 消息接收

    # 启动 COT 发送逻辑
    send_meshtastic_cot(args)
