from intent_and_sql_tools.common.vanna_base import VannaBase


class SQLVanna(VannaBase):
    def generate_sql(self, question: str) -> str:
        impl = self._ensure_impl()
        return impl.generate_sql(question=question)

    def generate_sql_from_context(self, context: str) -> str:
        return self.generate_sql(question=context)

    def run_sql(self, sql: str):
        impl = self._ensure_impl()
        return impl.run_sql(sql)
