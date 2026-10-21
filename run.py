"""运行课程项目。仅在明确传入 --reset 时重置演示数据。"""
import argparse
from app import create_app
from app.db import initialize_database


def main():
    parser = argparse.ArgumentParser(description="LabReserve 实验室设备预约与借用系统")
    parser.add_argument("--reset", action="store_true", help="清空本地数据库并重建演示数据")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8783, type=int)
    args = parser.parse_args()
    app = create_app()
    if args.reset:
        with app.app_context():
            initialize_database(reset=True)
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
