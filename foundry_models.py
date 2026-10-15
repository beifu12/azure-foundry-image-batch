#!/usr/bin/env python3
"""Unified entry point; the web and legacy CLI share the same deployment engine."""
import sys


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ('-h','--help'):
        print('Azure Foundry 多模型部署工作台\n'
              '  python foundry_models.py web [--host 127.0.0.1] [--port 8767]\n'
              '  python foundry_models.py {doctor,scan,deploy,setup-app} [选项]\n'
              '客户推荐使用 web；无需 Azure CLI。脚本选项见各命令 --help。')
        return 0
    if args[0]=='web':
        import web_app
        return web_app.main(args[1:])
    import image_batch
    return image_batch.main(args)


if __name__=='__main__':sys.exit(main())
