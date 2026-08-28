# Shizuku3エミュレータへのBACnet疎通確認（最小サンプル）
# 事前にShizuku3.exe（BACnetサーバ）を起動しておくこと
# bacpypes3を直接使用（アドレス直指定でデバイス探索が不要なため、
# IAmブロードキャストが届かないポート構成でも動作する）
import asyncio

from bacpypes3.app import Application
from bacpypes3.argparse import SimpleArgumentParser
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier

DEV = "127.0.0.1:47809"  # エミュレータのユニキャストポート


async def main():
    args = SimpleArgumentParser().parse_args(
        ["--address", "127.0.0.1/32:47810", "--instance", "3999", "--name", "probe"])
    app = Application.from_args(args)
    dev = Address(DEV)
    try:
        temp = await app.read_property(dev, ObjectIdentifier("analog-value,201"), "present-value")
        print("室温[C]:", temp)
        co2 = await app.read_property(dev, ObjectIdentifier("analog-value,203"), "present-value")
        print("CO2[ppm]:", co2)
        t0 = await app.read_property(dev, ObjectIdentifier("characterstring-value,303"), "present-value")
        print("シミュレーション時刻:", t0)

        # 加速度600倍で3秒間（シミュレーション30分）進める
        await app.write_property(dev, ObjectIdentifier("analog-value,301"), "present-value", 600.0)
        await asyncio.sleep(3)
        t1 = await app.read_property(dev, ObjectIdentifier("characterstring-value,303"), "present-value")
        print("加速度600で3秒後の時刻:", t1)
        await app.write_property(dev, ObjectIdentifier("analog-value,301"), "present-value", 0.0)

        print("疎通確認OK" if t0 != t1 else "時刻が進んでいない（要確認）")
    finally:
        app.close()


asyncio.run(main())
