"""Bind the unchanged qualified harness to this isolated replication source."""
from common import *
import environment as env
hive,hive_jvm,hive_verifier,external_root,providers=env.hive,env.hive_jvm,env.hive_verifier,env.external_root,env.providers
FREEZE=read(HERE/'FREEZE.json') if (HERE/'FREEZE.json').exists() else read(ROOT/'HIVE-FACTORIAL-003R1/FREEZE.json')
def forbid_models():
    async def forbidden(*args,**kwargs):raise AssertionError('No inference in scripted qualification')
    providers.ollama_chat=forbidden;providers.openai_chat=forbidden
