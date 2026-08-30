export function DemoOnboarding({ nextStep }: { nextStep: string }) {
  return (
    <section className="kw-demo-onboarding" aria-label="首次体验引导">
      <div>
        <span>空环境首次体验</span>
        <h2>三步生成第一个 Skill</h2>
      </div>
      <ol>
        <li><strong>添加数据或知识</strong><small>连接数据库、API、MCP 或上传历史案例。</small></li>
        <li><strong>描述目标</strong><small>说明要回答的问题、执行动作和结果形式。</small></li>
        <li><strong>生成并发布 Skill</strong><small>运行真实验证，确认证据后再发布。</small></li>
      </ol>
      <p role="status">{nextStep}</p>
    </section>
  );
}
