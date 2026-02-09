<!--
 * @Author: haoxingjun
 * @Date: 2026-02-05 14:25:26
 * @Email: haoxingjun@bytedance.com
 * @LastEditors: haoxingjun
 * @LastEditTime: 2026-02-09 18:12:43
 * @Description: file information
 * @Company: ByteDance
-->

# 火山引擎 VeFaaS 部署指南

本指南介绍如何将前端项目（React + Vite）及其代理服务部署到火山引擎函数服务（VeFaaS）。

## 1. 准备工作

我们已经为您准备了以下部署文件：

- **`server.js`**: 一个轻量级的 Node.js 服务器。
  - **注意**: 该文件已采用 **ES Module** 格式（`import`/`export`），与项目默认配置（`package.json` 中的 `"type": "module"`）保持一致。
  - 它负责托管 `dist/` 目录下的前端静态资源，并完整移植了 API 代理逻辑（文件上传、TOS 列表、VikingDB 调用）。
- **`dist/`**: 刚刚编译生成的前端静态资源。
- **`package.deploy.json`**: **专用部署配置**。为了避免在云端安装不必要的开发依赖（如 Puppeteer 导致安装失败），我们创建了这个精简版的配置文件。

## 2. 打包步骤 (关键)

请严格按照以下步骤操作，**避免常见的路径错误**：

1.  **准备文件**:
    - 确保您位于 `contract-review-assistant` 目录下。
    - 将 `package.deploy.json` 复制一份并重命名为 `package.json`。（VeFaaS 只识别 `package.json`，且必须位于 zip 包的根目录）。
      - _建议将原有的 `package.json` 暂时备份。_

2.  **创建压缩包**:
    - 选中以下三个文件/文件夹：
      - `dist` (文件夹)
      - `server.js`
      - `package.json` (使用刚才重命名的精简版)
    - **右键 -> 压缩** 为 `deploy.zip`。

    > **重要警告**:
    >
    > - **请勿** 压缩整个 `contract-review-assistant` 文件夹！
    > - **请勿** 将文件放在任何子文件夹中！
    > - 打开 zip 包预览时，您应该直接看到 `server.js`，而不是看到一个文件夹。

## 3. 部署到 VeFaaS

1.  登录火山引擎控制台，进入 **函数服务 (VeFaaS)**。
2.  点击 **创建函数**。
3.  **基本配置**:
    - **函数名称**: 例如 `contract-review-frontend`。
    - **运行环境**: 推荐选择 **Node.js 20** (或 Node.js 18+)。
4.  **代码配置**:
    - **代码来源**: 选择 **上传 Zip 包**，上传刚才创建的 `deploy.zip`。
    - **启动命令**: `node server.js`
    - **监听端口**: `9000`
5.  **依赖安装**:
    - 请务必开启 **在线安装依赖** (Online Build/Install)，系统会根据 `package.json` 自动安装 `express` 等必要库。
6.  **环境变量配置 (至关重要)**:
    您**必须**在函数配置中添加以下环境变量，否则服务将无法启动或无法访问云资源：

    | 键 (Key)                | 值 (Value)                     | 说明                               |
    | :---------------------- | :----------------------------- | :--------------------------------- |
    | `VOLCENGINE_ACCESS_KEY` | `您的AK`                       | 必填，用于访问 TOS 和 VikingDB     |
    | `VOLCENGINE_SECRET_KEY` | `您的SK`                       | 必填，用于访问 TOS 和 VikingDB     |
    | `VITE_UPLOAD_BUCKET`    | `agentkit-platform-2100045928` | (建议) TOS Bucket 名称             |
    | `VITE_UPLOAD_REGION`    | `cn-beijing`                   | (可选) TOS Region，默认 cn-beijing |
    | `VITE_UPLOAD_PATH`      | `upload/contract_review/`      | (可选) 上传路径前缀                |

    > **提示**: 请从您的 `.env` 文件中复制这些值（如果有）。

7.  **触发器**:
    - 创建一个 **HTTP 触发器** (Web Function)，这将为您提供一个公网访问 URL。

## 4. 常见问题排查

- **Error: Cannot find module '/opt/bytefaas/server.js'**:
  - **原因**：压缩包结构错误。您可能压缩了文件夹，或者 `server.js` 不在 zip 包的根目录下。
  - **解决**：解压您的 zip 包检查。确保打开 zip 包后**直接**看到 `server.js`，而不是看到一个文件夹。
- **Error: Cannot find package 'express'**:
  - **原因**：依赖安装失败。原因可能是使用了包含复杂依赖（如 puppeteer）的原版 `package.json`。
  - **解决**：请务必使用我们提供的 **`package.deploy.json`** (重命名为 `package.json`) 进行部署。
- **Error: require is not defined**:
  - **原因**：模块类型不匹配。
  - **解决**：确保使用了最新的 `server.js` (我们已将其更新为 ES Module 格式)。
- **Missing TOS credentials**:
  - 检查环境变量 `VOLCENGINE_ACCESS_KEY` 和 `VOLCENGINE_SECRET_KEY` 是否已正确配置。

## 5. 验证

部署完成后，访问 HTTP 触发器提供的 URL，您应该能看到合同审核助手的前端界面，并且文件上传、审核功能均能正常工作。
