package com.psyche.kelivo.quickjs

import io.flutter.plugin.common.BinaryMessenger
import java.nio.ByteBuffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

/**
 * The six packages whose METADATA is HJSON, not JSON: their keys are unquoted, so
 * `org.json` alone rejects them and `listTools` drops them. Every fixture below is
 * the block copied out of `assets/operit_packages/<name>.js` by
 * `scripts/patch_metadata_hjson_test.py` -- the same expression the parser uses --
 * rather than retyped, because quoting is what makes the block HJSON and a fixture
 * typed by hand could stop being HJSON while the test stayed green. Each fixture is
 * the whole `/* METADATA ... */` block rather than the inside of one, because the
 * marker is what `parseMetadata` searches the source for: without it, all six come
 * back null.
 *
 * If the parse ever goes back to `JSONObject(text)` alone, all six fail: none of
 * these blocks is JSON. That is the regression this exists to catch, and it is why
 * each package is named in its own test rather than counted.
 *
 * Each assertion expects the name its own block declares rather than the asset's
 * file name, which is why automatic_ui_subagent expects the upstream's
 * `Automatic_ui_subagent`: capitalised in the asset, not typed that way here.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class OperitJsRuntimeMetadataTest {
    private val runtime = OperitJsRuntime(RuntimeEnvironment.getApplication(), Messenger())

    /** `MethodChannel` only stores the messenger; nothing is dispatched here. */
    private class Messenger : BinaryMessenger {
        override fun send(channel: String, message: ByteBuffer?) = Unit

        override fun send(
            channel: String,
            message: ByteBuffer?,
            callback: BinaryMessenger.BinaryReply?,
        ) = Unit

        override fun setMessageHandler(
            channel: String,
            handler: BinaryMessenger.BinaryMessageHandler?,
        ) = Unit
    }

    private companion object {
        val AUTOMATIC_UI_SUBAGENT = """
/* METADATA
{
    name: "Automatic_ui_subagent"

    display_name: {
      zh: "自动化AutoGLM子代理"
      en: "Automated AutoGLM Sub-agent"
    }description: {
        zh: '''
兼容AutoGLM，提供基于独立UI控制器模型（例如 autoglm-phone-9b）的高层UI自动化子代理工具，用于根据自然语言意图自动规划并执行点击/输入/滑动等一系列界面操作。
当用户提出需要帮忙完成某个界面操作任务（例如打开应用、搜索内容、在多个页面之间完成一套步骤）时，可以调用本包由子代理自动规划和执行具体步骤。
''',
        en: '''
Compatible with AutoGLM. Provides a high-level UI automation sub-agent based on an independent UI-controller model (e.g. autoglm-phone-9b). It can plan and execute a sequence of UI actions (tap/type/swipe) from natural-language intent.
When the user asks you to complete a UI task (e.g. open an app, search content, or finish a multi-step workflow across pages), you can call this package and let the sub-agent plan and execute the steps.
'''
    }
    category: "Automatic"

    tools: []

    states: [
        {
            id: "virtual_display"
            condition: "ui.virtual_display"
            inheritTools: true
            tools: [
                {
                    name: "usage_advice"
                    description: {
                        zh: '''
 UI子代理使用建议：

 - 屏幕选择规则（重要）：不传 agent_id 或传 'default' => 主屏幕；传入且不为 'default' => 对应虚拟屏会话（虚拟屏必须可用，否则会失败）。

 - 会话复用（重要）：多次调用尽量复用同一个 agent_id（沿用上一次返回的 data.agentId），保持在同一虚拟屏/同一应用上下文内。
 - 启动前置（非常重要）：当你第一次使用某个 agent_id（新建或更换 agent_id）时，intent 开头必须写“启动XXX应用 ...”，让子代理直接执行 Launch，而不是在桌面自己找。
 - 对话无状态（重要）：每次调用对子代理都是全新对话，intent 需要自带上下文，建议固定模板：
   当前任务已经完成: ...
   你需要在此基础上进一步完成: ...
   可能用到的信息: ...
 - 意图必须自包含（重要）：禁止使用“这五个/继续/同上/刚才说的”等指代。
   - 多对象任务必须在“可能用到的信息”里给出清单（按界面顺序），并明确当前要处理哪个（例如第1个酒店）。
   - 若清单未知，本次调用先让子代理从当前页面识别并复述清单，再进行下一步（必要时拆成多次调用）。
 - 对齐推进（重要）：不要一次调用里同时做“收集清单 + 处理清单全部对象”。应拆成：先清单，再按 A→B→C 逐项处理。
 - 并行优先（重要）：互不依赖的子任务（多平台搜索/多入口确认/同一对象的信息提取分工）优先用 run_subagent_parallel_virtual 并行；并行时每个子代理建议不同 agent_id 避免互相干扰.
 - 并行资源约束（重要）：并行分支数必须受“可用独立App数量/可用虚拟屏数量”限制。
   - 同一个App/同一个包名，不能同时存在于两个虚拟屏/两个 agent_id 中并行操作（会导致应用状态错乱/坏掉）。
   - 并行分支数不得超过“可同时存在的独立App数量”（例如只有2个独立App可用，就最多2并行）。
   - 并行调用必须传入 target_app_i=目标应用名（每个 intent_i 对应一个 target_app_i），用于冲突检测；所有启用分支的 target_app_i 必须互不相同.
   - 第2次/第N次并行（重试或第二轮任务）不得因为“想更快”而擅自提高并行度；应保持同样的并行上限，只重试失败分支，或改为串行.
 - 失败与完成（重要）：半成功/误判完成不算完成；应继续纠错推进。仅在连续 2-3 次失败仍无法推进时才停止，并明确失败原因与可选替代方案.
 - 例子（详细：1并行 + 2串行）

   例子1（并行：多平台同时找同一酒店的差评要点）
   目标：同时在 大众点评/美团/携程 搜索“XX酒店”，各自提取“近一年差评Top3要点 + 原文引用 + 日期”，最后主Agent合并.
   调用流程：
   1) 主Agent 一次并行：
      - 调用 run_subagent_parallel_virtual，给每个子代理一个互不干扰的 agent_id（例如 dp_1 / mt_1 / xc_1）。
      - intent_1（大众点评）示例：
        当前任务已经完成: 无
        你需要在此基础上进一步完成: 打开大众点评，搜索“XX酒店”，进入酒店详情，进入评价/差评/低分区，提取近一年差评Top3要点，并把每条要点附带1句原文引用+日期.
        可能用到的信息: 目标酒店名=XX酒店；输出格式=1)要点 2)引用 3)日期；如果搜到多个同名酒店，必须先确认地址/商圈与目标一致.
      - intent_2（美团）/ intent_3（携程）同理，各自写清 app、路径、输出格式.
   2) 主Agent 汇总：读取并行返回 results，合并三个平台的提取结果.
   3) 只重试失败分支：若 results 里只有美团分支失败，则只对美团再发起一次（不要重跑点评/携程）。
      - 例如再次调用 run_subagent_virtual（或再次 run_subagent_parallel_virtual 但只填 intent_2），并补充纠错信息：
        当前任务已经完成: 上次在美团搜索到酒店列表，但未能进入评价页（可能入口在“点评/评价”Tab）。
        你需要在此基础上进一步完成: 重新打开美团搜索“XX酒店”，进入正确的酒店详情页，找到“评价/点评”入口并进入差评/低分区，按同样格式输出Top3.
        可能用到的信息: 若页面出现“住客点评/全部评价/差评”多入口，优先选择“全部评价”再筛选“差评/低分”。

   例子2（串行：先清单，再按 A→B→C 逐项处理）
   目标：在携程酒店列表页，先列出前5家酒店；然后只处理第1家酒店的差评要点；处理完再处理第2家……
   调用流程：
   1) 清单阶段（一次 run_subagent_virtual）：
      - 主Agent 调用 run_subagent_virtual(intent=..., agent_id="ctrip_1")
      - intent 示例：
        当前任务已经完成: 无
        你需要在此基础上进一步完成: 打开携程，搜索“杭州 西湖 酒店”，进入列表页；把当前屏幕能看到的酒店按从上到下顺序列出前5个（名称+价格/评分如可见），并停留在列表页不要进入详情.
        可能用到的信息: 输出必须包含清单序号1-5；若需要滚动才能凑满5个可以滚动一次，但仍要保持顺序.
      - 该次返回 data.agentId 记为 A（后续复用）
   2) 单对象阶段：处理“清单第1家”（一次 run_subagent_virtual，复用 agent_id=A）
      - intent 示例：
        当前任务已经完成: 已获得酒店清单（1)酒店A 2)酒店B 3)酒店C 4)酒店D 5)酒店E），当前停留在列表页.
        你需要在此基础上进一步完成: 进入酒店A详情页，找到评价页并筛选差评/低分，提取差评Top3要点（每条含1句原文引用）。完成后返回列表页并确认列表顶部仍是酒店A/B/C顺序.
        可能用到的信息: 目标对象=清单第1家=酒店A；如果进入后发现标题不是酒店A则立刻返回列表并重新点击正确条目.
   3) 继续处理第2家/第3家……（每次都复用 agent_id=A，并在 intent 中显式写“已完成/下一步/关键信息”，以及“当前目标=清单第2家=酒店B”）。

   例子3（串行：发消息，强调“页面确认+会话复用”）
   目标：在微信给“张三”发送“我到楼下了”，并确认发送成功.
   调用流程：
   1) 打开并定位会话（一次 run_subagent_virtual）：
      - 主Agent 调用 run_subagent_virtual(intent=..., agent_id="wechat_1")
      - intent 示例：
        当前任务已经完成: 无
        你需要在此基础上进一步完成: 打开微信，进入聊天列表，搜索联系人“张三”，打开与“张三”的聊天页面；必须确认页面顶部标题=张三.
        可能用到的信息: 如果搜索结果有多个“张三”，需要根据头像/备注/地区等二次确认；不确定时返回并说明.
      - 该次返回 data.agentId 记为 W（后续复用）
   2) 发送并二次确认（一次 run_subagent_virtual，复用 agent_id=W）：
      - intent 示例：
        当前任务已经完成: 已打开与“张三”的聊天页，顶部标题=张三.
        你需要在此基础上进一步完成: 输入并发送消息“我到楼下了”；发送后在消息列表中确认该消息出现在最新一条且无明显发送失败标记（如红色感叹号）.
        可能用到的信息: 若出现权限弹窗/键盘遮挡，先处理弹窗再继续；若发送失败，尝试重发一次并说明原因.
 ''',
        en: '''
 UI sub-agent usage advice:

 - Screen selection rule (important): omitted agent_id or 'default' => main screen; provided and not 'default' => the requested virtual display session (must be available, otherwise the run fails).

 - Session reuse (important): reuse the same agent_id across calls when possible (use the returned data.agentId) to stay in the same virtual display and app context.
 - Launch first (very important): when you first use an agent_id (new or changed), the intent must start with "Launch <app> ..." so the sub-agent performs a Launch directly instead of searching from the home screen.
 - Stateless per call (important): each call is a new conversation; include all necessary context. Recommended template: Completed so far / Next objective / Useful info.
 - Self-contained intent (important): do not use references like "those five / continue / same as above".
   - For multi-item tasks, list items in "Useful info" (in on-screen order) and specify which one to handle now.
   - If the list is unknown, first ask the sub-agent to identify and restate the list from the current screen, then proceed.
 - Step-by-step alignment (important): do not combine "collect list" + "process all items" in one call. Split into: list first, then process A→B→C.
 - Prefer parallelism (important): for independent subtasks (multi-platform search / multi-entry verification / extraction sub-tasks for the same object), use run_subagent_parallel_virtual. Use different agent_id per branch to avoid interference.
 - Parallel resource constraints (important): parallel branches are limited by available independent apps / virtual displays.
   - The same app/package must not be operated in parallel across two virtual displays / agent_id (it can break app state).
   - Branch count must not exceed available independent apps.
   - Parallel calls must provide target_app_i for each enabled intent_i; all target_app_i must be different.
   - Do not increase parallelism in later rounds; keep the same upper bound and only retry failed branches, or switch to serial.
 - Failure vs done (important): partial success is not done; keep correcting and progressing. Only stop after 2-3 consecutive failures with a clear reason and alternatives.
'''
                    }
                    advice: true
                    parameters: []
                }

                {
                    name: "run_subagent_main"
                    description: {
                        zh: "在主屏幕运行 UI 子代理（强制主屏）。",
                        en: "Run the UI sub-agent on the main screen (forced main screen)."
                    }
                    parameters: [
                        {
                            name: "intent"
                            description: {
                                zh: "任务意图描述",
                                en: "Task intent description"
                            }
                            type: "string"
                            required: true
                        }
                        {
                            name: "target_app"
                            description: {
                                zh: "目标应用名/包名（可选）",
                                en: "Target app name/package (optional)"
                            }
                            type: "string"
                            required: false
                        }
                        {
                            name: "max_steps"
                            description: {
                                zh: "最大执行步数（默认20）",
                                en: "Maximum execution steps (default: 20)"
                            }
                            type: "number"
                            required: false
                        }
                    ]
                }

                {
                    name: "run_subagent_virtual"
                    description: {
                        zh: "在虚拟屏幕会话运行 UI 子代理（强制虚拟屏）。",
                        en: "Run the UI sub-agent on a virtual-display session (forced virtual screen)."
                    }
                    parameters: [
                        {
                            name: "intent"
                            description: {
                                zh: "任务意图描述",
                                en: "Task intent description"
                            }
                            type: "string"
                            required: true
                        }
                        {
                            name: "target_app"
                            description: {
                                zh: "目标应用名/包名（可选）",
                                en: "Target app name/package (optional)"
                            }
                            type: "string"
                            required: false
                        }
                        {
                            name: "max_steps"
                            description: {
                                zh: "最大执行步数（默认20）",
                                en: "Maximum execution steps (default: 20)"
                            }
                            type: "number"
                            required: false
                        }
                        {
                            name: "agent_id"
                            description: {
                                zh: "虚拟屏会话 agent_id（必须为非 'default'；可传入复用，或留空复用上次返回的 data.agentId）。",
                                en: "Virtual-screen session agent_id (must be non-'default'; pass to reuse, or omit to reuse returned data.agentId)."
                            }
                            type: "string"
                            required: false
                        }
                    ]
                }

                {
                    name: "run_subagent_parallel_virtual"
                    description: {
                        zh: '''
并行运行 1-4 个 UI 子代理（强制虚拟屏）。

 注意：并行调用时，每个子代理对它自身都是全新对话，因此 intent_1..4 需要由主Agent分别写清楚“已完成/下一步/关键信息”。
 建议并行时每个子代理使用不同的 agent_id（必须显式传入，且不能为 'default'），避免操作同一虚拟屏幕造成冲突。
 如果并行任务中仅有部分子代理失败，则只对失败的子代理继续发起后续调用（补充纠错信息、提高约束），不要让已成功的子代理重复执行。
 每个 intent_i 必须自包含；建议不同 agent_id；只重试失败的 intent_i。
 典型场景：多平台并行搜索；同一对象多入口确认/交叉校验；把“同一对象A”的分工并行做完后再进入B.
 '''
                    }
                    parameters: [
                        {
                            name: "intent_1"
                            description: {
                                zh: "第1个子代理意图（推荐使用：当前任务已经完成/你需要进一步完成/可能用到的信息 三段式）",
                                en: "Intent for sub-agent #1 (recommended template: Completed so far / Next objective / Useful info)."
                            }
                            type: "string"
                            required: true
                        }
                        {
                            name: "target_app_1"
                            description: {
                                zh: "第1个子代理目标应用名（必填，用于并行冲突检测；各分支必须不同）",
                                en: "Target app name for sub-agent #1 (required for conflict detection; must be different across branches)."
                            }
                            type: "string"
                            required: true
                        }
                        {
                            name: "max_steps_1"
                            description: {
                                zh: "第1个子代理最大步数（默认20）",
                                en: "Max steps for sub-agent #1 (default: 20)."
                            }
                            type: "number"
                            required: false
                        }
                        {
                            name: "agent_id_1"
                            description: {
                                zh: "第1个子代理 agent_id（必填，且不能为 'default'；用于指定虚拟屏会话；并行建议不同）",
                                en: "agent_id for sub-agent #1 (required, must not be 'default'; selects a virtual-display session; use different agent_id per branch)."
                            }
                            type: "string"
                            required: true
                        }

                        {
                            name: "intent_2"
                            description: {
                                zh: "第2个子代理意图（可选）",
                                en: "Intent for sub-agent #2 (optional)."
                            }
                            type: "string"
                            required: false
                        }
                        {
                            name: "target_app_2"
                            description: {
                                zh: "第2个子代理目标应用名（当 intent_2 存在时必填；各分支必须不同）",
                                en: "Target app name for sub-agent #2 (required when intent_2 is provided; must be different across branches)."
                            }
                            type: "string"
                            required: false
                        }
                        {
                            name: "max_steps_2"
                            description: {
                                zh: "第2个子代理最大步数（默认20）",
                                en: "Max steps for sub-agent #2 (default: 20)."
                            }
                            type: "number"
                            required: false
                        }
                        {
                            name: "agent_id_2"
                            description: {
                                zh: "第2个子代理 agent_id（当 intent_2 存在时必填，且不能为 'default'；用于指定虚拟屏会话；并行建议不同）",
                                en: "agent_id for sub-agent #2 (required when intent_2 is provided, must not be 'default'; selects a virtual-display session; use different agent_id per branch)."
                            }
                            type: "string"
                            required: false
                        }

                        {
                            name: "intent_3"
                            description: {
                                zh: "第3个子代理意图（可选）",
                                en: "Intent for sub-agent #3 (optional)."
                            }
                            type: "string"
                            required: false
                        }
                        {
                            name: "target_app_3"
                            description: {
                                zh: "第3个子代理目标应用名（当 intent_3 存在时必填；各分支必须不同）",
                                en: "Target app name for sub-agent #3 (required when intent_3 is provided; must be different across branches)."
                            }
                            type: "string"
                            required: false
                        }
                        {
                            name: "max_steps_3"
                            description: {
                                zh: "第3个子代理最大步数（默认20）",
                                en: "Max steps for sub-agent #3 (default: 20)."
                            }
                            type: "number"
                            required: false
                        }
                        {
                            name: "agent_id_3"
                            description: {
                                zh: "第3个子代理 agent_id（当 intent_3 存在时必填，且不能为 'default'）",
                                en: "agent_id for sub-agent #3 (required when intent_3 is provided; must not be 'default')."
                            }
                            type: "string"
                            required: false
                        }

                        {
                            name: "intent_4"
                            description: {
                                zh: "第4个子代理意图（可选）",
                                en: "Intent for sub-agent #4 (optional)."
                            }
                            type: "string"
                            required: false
                        }
                        {
                            name: "target_app_4"
                            description: {
                                zh: "第4个子代理目标应用名（当 intent_4 存在时必填；各分支必须不同）",
                                en: "Target app name for sub-agent #4 (required when intent_4 is provided; must be different across branches)."
                            }
                            type: "string"
                            required: false
                        }
                        {
                            name: "max_steps_4"
                            description: {
                                zh: "第4个子代理最大步数（默认20）",
                                en: "Max steps for sub-agent #4 (default: 20)."
                            }
                            type: "number"
                            required: false
                        }
                        {
                            name: "agent_id_4"
                            description: {
                                zh: "第4个子代理 agent_id（当 intent_4 存在时必填，且不能为 'default'）",
                                en: "agent_id for sub-agent #4 (required when intent_4 is provided; must not be 'default')."
                            }
                            type: "string"
                            required: false
                        }
                    ]
                }

                {
                    name: "close_all_virtual_displays"
                    description: {
                        zh: "关闭所有虚拟屏幕。",
                        en: "Close all virtual displays."
                    }
                    parameters: []
                }

                {
                    name: "run_subagent_main"
                    description: {
                        zh: "在主屏幕运行 UI 子代理（强制主屏）。",
                        en: "Run the UI sub-agent on the main screen (forced main screen)."
                    }
                    parameters: [
                        {
                            name: "intent"
                            description: {
                                zh: "任务意图描述",
                                en: "Task intent description"
                            }
                            type: "string"
                            required: true
                        }
                        {
                            name: "target_app"
                            description: {
                                zh: "目标应用名/包名（可选）",
                                en: "Target app name/package (optional)"
                            }
                            type: "string"
                            required: false
                        }
                        {
                            name: "max_steps"
                            description: {
                                zh: "最大执行步数（默认20）",
                                en: "Maximum execution steps (default: 20)"
                            }
                            type: "number"
                            required: false
                        }
                    ]
                }
            ]
        }

        {
            id: "main_screen"
            condition: "!ui.virtual_display"
            inheritTools: true
            tools: [
                {
                    name: "usage_advice"
                    description: {
                        zh: '''
 UI子代理使用建议（主屏模式）：

 - 屏幕选择规则（重要）：主屏模式始终在主屏幕执行；agent_id 会被忽略/不适用。

 - 启动前置（非常重要）：当你第一次需要操作某个应用时，intent 开头必须写“启动XXX应用 ...”，让子代理直接执行 Launch，而不是在桌面自己找。
 - 对话无状态（重要）：每次调用对子代理都是全新对话，intent 必须自带上下文，建议固定模板：
   当前任务已经完成: ...
   你需要在此基础上进一步完成: ...
   可能用到的信息: ...
 - 意图必须自包含（重要）：禁止使用“这五个/继续/同上/刚才说的”等指代.
 - 严格串行（重要）：主屏模式不支持并行工具；一次只做一个明确子目标，必要时拆成多次调用.
 - 不支持会话复用（重要）：主屏模式不支持 agent_id，会话复用相关策略不适用.
 - 失败与完成（重要）：半成功不算完成；应继续纠错推进.仅在连续 2-3 次失败仍无法推进时才停止，并明确失败原因与可选替代方案.
 ''',
                        en: '''
 UI sub-agent usage advice (main-screen mode):

 - Screen selection rule (important): main-screen mode always operates on the main screen; agent_id is ignored / not applicable.

 - Launch first (very important): when you need to operate an app for the first time, the intent must start with "Launch <app> ..." so the sub-agent performs Launch directly.
 - Stateless per call (important): each call is a new conversation; include all context. Recommended template: Completed so far / Next objective / Useful info.
 - Self-contained intent (important): do not use references like "those five / continue / same as above".
 - Strictly serial (important): main-screen mode does not support parallel tools; do one clear sub-goal per call.
 - No session reuse (important): main-screen mode does not support agent_id; session reuse strategies do not apply.
 - Failure vs done (important): partial success is not done; keep progressing. Only stop after 2-3 consecutive failures with a clear reason and alternatives.
'''
                    }
                    advice: true
                    parameters: []
                }

                {
                    name: "run_subagent_main"
                    description: {
                        zh: '''
 在主屏幕运行 UI 子代理（强制主屏）。

 注意：主屏模式不支持虚拟屏会话与并行工具。
 ''',
                        en: '''
 Run the UI sub-agent on the main screen (forced main screen).

 Note: main-screen mode does not support virtual sessions and does not support parallel tools.
 '''
                    }
                    parameters: [
                        {
                            name: "intent"
                            description: {
                                zh: "任务意图描述，例如：'打开微信并发送一条消息' 或 '在B站搜索某个视频'",
                                en: "Task intent description, e.g. 'Open WeChat and send a message' or 'Search a video on Bilibili'."
                            }
                            type: "string"
                            required: true
                        }
                        {
                            name: "target_app"
                            description: {
                                zh: "目标应用名/包名（建议传入，用于在虚拟屏未创建时先执行一次默认 Launch 预热虚拟屏，避免在主屏误操作；约定：当用户要求分析当前屏幕/页面内容时不要传 target_app，也不要预热虚拟屏）",
                                en: "Target app name/package (recommended). Helps with a default Launch/warm-up and avoids operating on the wrong screen. Convention: when the user asks to analyze the current screen/page, do not pass target_app and do not prewarm the virtual display."
                            }
                            type: "string"
                            required: false
                        }
                        {
                            name: "max_steps"
                            description: {
                                zh: "最大执行步数，默认20，可根据任务复杂度调整。",
                                en: "Maximum execution steps (default: 20). Adjust based on task complexity."
                            }
                            type: "number"
                            required: false
                        }
                    ]
                }
            ]
        }
    ]
 }*/
"""

        val CODE_RUNNER = """
/* METADATA
{
  name: code_runner
  display_name: {
    zh: "代码运行器"
    en: "Code Runner"
  }
  description: { zh: "提供多语言代码执行能力，支持JavaScript、Python、Ruby、Go、Rust、C和C++脚本的运行。可直接执行代码字符串或运行外部文件，适用于快速测试、自动化脚本和教学演示。", en: "Multi-language code execution. Supports running JavaScript, Python, Ruby, Go, Rust, C and C++ scripts. You can execute code strings directly or run external files, useful for quick tests, automation, and demos." }
  enabledByDefault: true
  
  category: "Development"
  // Multiple tools in this package
  tools: [
    {
      name: run_javascript_es5
      description: { zh: "运行自定义 JavaScript (ES5) 脚本。会捕获 console.log 的输出以及最终的返回值。", en: "Run custom JavaScript (ES5). Captures console.log output and the final return value." }
      // This tool takes parameters
      parameters: [
        {
          name: script
          description: { zh: "要执行的 JavaScript 脚本内容", en: "JavaScript script content to execute." }
          type: string
          required: true
        }
      ]
    },
    {
      name: run_javascript_file
      description: { zh: "运行 JavaScript (ES5) 文件。会捕获 console.log 的输出以及最终的返回值。", en: "Run a JavaScript (ES5) file. Captures console.log output and the final return value." }
      parameters: [
        {
          name: file_path
          description: { zh: "JavaScript 文件路径", en: "Path to the JavaScript file." }
          type: string
          required: true
        }
      ]
    },
    {
      name: run_javascript_node
      description: { zh: "使用 Node.js 运行 JavaScript 脚本。返回 stdout/stderr 输出。", en: "Run JavaScript using Node.js. Returns stdout/stderr output." }
      parameters: [
        {
          name: script
          description: { zh: "要执行的 JavaScript 脚本内容", en: "JavaScript script content to execute." }
          type: string
          required: true
        },
        {
          name: node_flags
          description: { zh: "Node.js 解释器选项，默认为空。可自定义如 --trace-warnings、--no-warnings 等", en: "Node.js interpreter flags (default: empty). Examples: --trace-warnings, --no-warnings." }
          type: string
          required: false
        }
      ]
    },
    {
      name: run_javascript_node_file
      description: { zh: "使用 Node.js 运行 JavaScript 文件。返回 stdout/stderr 输出。", en: "Run a JavaScript file using Node.js. Returns stdout/stderr output." }
      parameters: [
        {
          name: file_path
          description: { zh: "JavaScript 文件路径", en: "Path to the JavaScript file." }
          type: string
          required: true
        },
        {
          name: node_flags
          description: { zh: "Node.js 解释器选项，默认为空。可自定义如 --trace-warnings、--no-warnings 等", en: "Node.js interpreter flags (default: empty). Examples: --trace-warnings, --no-warnings." }
          type: string
          required: false
        }
      ]
    },
    {
      name: install_node_packages
      description: { zh: "在持久 Node 工作目录(${'$'}HOME/.code_runner/node)中安装 pnpm 包", en: "Install packages with pnpm in the persistent Node workspace (${'$'}HOME/.code_runner/node)." }
      parameters: [
        {
          name: packages
          description: { zh: "要安装的包名（用 | 分隔），例如 axios|lodash|@types/node", en: "Package names to install, separated by | (e.g. axios|lodash|@types/node)." }
          type: string
          required: true
        },
        {
          name: save_dev
          description: { zh: "是否作为开发依赖安装（pnpm add -D）", en: "Whether to install as dev dependency (pnpm add -D)." }
          type: boolean
          required: false
        }
      ]
    },
    {
      name: install_python_packages
      description: { zh: "在持久虚拟环境(~/.code_runner/py)中安装 Python 包（使用 pip）", en: "Install Python packages in the persistent virtual environment (~/.code_runner/py) using pip." }
      parameters: [
        {
          name: packages
          description: { zh: "要安装的包名（用 | 分隔），例如 numpy|pydantic==2.*", en: "Package names to install, separated by | (e.g. numpy|pydantic==2.*)." }
          type: string
          required: true
        },
        {
          name: upgrade
          description: { zh: "是否升级已安装的包，等价于 pip -U", en: "Whether to upgrade already installed packages (equivalent to pip -U)." }
          type: boolean
          required: false
        }
      ]
    },
    {
      name: run_python
      description: { zh: "运行自定义 Python 脚本。会捕获 print 函数的输出。", en: "Run custom Python scripts. Captures output from print()." }
      parameters: [
        {
          name: script
          description: { zh: "要执行的 Python 脚本内容", en: "Python script content to execute." }
          type: string
          required: true
        },
        {
          name: python_flags
          description: { zh: "Python 解释器选项，默认为空。可自定义如 -O（优化）、-u（无缓冲）等", en: "Python interpreter flags (default: empty). Examples: -O (optimize), -u (unbuffered)." }
          type: string
          required: false
        },
        {
          name: script_args
          description: { zh: "传递给 Python 脚本的参数，使用 | 分隔，例如 arg1|arg with space|--name=alice", en: "Arguments passed to the Python script, separated by | (e.g. arg1|arg with space|--name=alice)." }
          type: string
          required: false
        }
      ]
    },
    {
      name: run_python_file
      description: { zh: "运行 Python 文件。会捕获 print 函数的输出。", en: "Run a Python file. Captures output from print()." }
      parameters: [
        {
          name: file_path
          description: { zh: "Python 文件路径", en: "Path to the Python file." }
          type: string
          required: true
        },
        {
          name: python_flags
          description: { zh: "Python 解释器选项，默认为空。可自定义如 -O（优化）、-u（无缓冲）等", en: "Python interpreter flags (default: empty). Examples: -O (optimize), -u (unbuffered)." }
          type: string
          required: false
        },
        {
          name: script_args
          description: { zh: "传递给 Python 文件的参数，使用 | 分隔，例如 arg1|arg with space|--name=alice", en: "Arguments passed to the Python file, separated by | (e.g. arg1|arg with space|--name=alice)." }
          type: string
          required: false
        }
      ]
    },
    {
      name: run_ruby
      description: { zh: "运行自定义 Ruby 脚本", en: "Run custom Ruby scripts." }
      parameters: [
        {
          name: script
          description: { zh: "要执行的 Ruby 脚本内容", en: "Ruby script content to execute." }
          type: string
          required: true
        },
        {
          name: ruby_flags
          description: { zh: "Ruby 解释器选项，默认为空。可自定义如 --jit（JIT 编译）等", en: "Ruby interpreter flags (default: empty). Example: --jit." }
          type: string
          required: false
        }
      ]
    },
    {
      name: run_ruby_file
      description: { zh: "运行 Ruby 文件", en: "Run a Ruby file." }
      parameters: [
        {
          name: file_path
          description: { zh: "Ruby 文件路径", en: "Path to the Ruby file." }
          type: string
          required: true
        },
        {
          name: ruby_flags
          description: { zh: "Ruby 解释器选项，默认为空。可自定义如 --jit（JIT 编译）等", en: "Ruby interpreter flags (default: empty). Example: --jit." }
          type: string
          required: false
        }
      ]
    },
    {
      name: run_go
      description: { zh: "运行自定义 Go 代码", en: "Run custom Go code." }
      parameters: [
        {
          name: script
          description: { zh: "要执行的 Go 代码内容", en: "Go source code to execute." }
          type: string
          required: true
        },
        {
          name: build_flags
          description: { zh: "Go 编译选项，默认为空。可自定义如 -ldflags='-s -w'（减小二进制体积）等", en: "Go build flags (default: empty). Example: -ldflags='-s -w' (reduce binary size)." }
          type: string
          required: false
        }
      ]
    },
    {
      name: run_go_file
      description: { zh: "运行 Go 文件", en: "Run a Go file." }
      parameters: [
        {
          name: file_path
          description: { zh: "Go 文件路径", en: "Path to the Go file." }
          type: string
          required: true
        },
        {
          name: build_flags
          description: { zh: "Go 编译选项，默认为空。可自定义如 -ldflags='-s -w'（减小二进制体积）等", en: "Go build flags (default: empty). Example: -ldflags='-s -w' (reduce binary size)." }
          type: string
          required: false
        }
      ]
    },
    {
      name: run_rust
      description: { zh: "运行自定义 Rust 代码", en: "Run custom Rust code." }
      parameters: [
        {
          name: script
          description: { zh: "要执行的 Rust 代码内容", en: "Rust source code to execute." }
          type: string
          required: true
        },
        {
          name: cargo_flags
          description: { zh: "Cargo 构建选项，默认为 --release。可自定义如 空字符串（调试模式）、--release --features xxx 等", en: "Cargo build flags (default: --release). Examples: empty string (debug), --release --features xxx." }
          type: string
          required: false
        }
      ]
    },
    {
      name: run_rust_file
      description: { zh: "运行 Rust 文件", en: "Run a Rust file." }
      parameters: [
        {
          name: file_path
          description: { zh: "Rust 文件路径", en: "Path to the Rust file." }
          type: string
          required: true
        },
        {
          name: cargo_flags
          description: { zh: "Cargo 构建选项，默认为 --release。可自定义如 空字符串（调试模式）、--release --features xxx 等", en: "Cargo build flags (default: --release). Examples: empty string (debug), --release --features xxx." }
          type: string
          required: false
        }
      ]
    },
    {
      name: run_c
      description: { zh: "运行自定义 C 代码", en: "Run custom C code." }
      parameters: [
        {
          name: script
          description: { zh: "要执行的 C 代码内容", en: "C source code to execute." }
          type: string
          required: true
        },
        {
          name: compile_flags
          description: { zh: "编译选项，默认为 -O3 -march=native -fopenmp。可自定义如 -O2、-O0 -g 等", en: "Compile flags (default: -O3 -march=native -fopenmp). Examples: -O2, -O0 -g." }
          type: string
          required: false
        }
      ]
    },
    {
      name: run_c_file
      description: { zh: "运行 C 文件", en: "Run a C file." }
      parameters: [
        {
          name: file_path
          description: { zh: "C 文件路径", en: "Path to the C file." }
          type: string
          required: true
        },
        {
          name: compile_flags
          description: { zh: "编译选项，默认为 -O3 -march=native -fopenmp。可自定义如 -O2、-O0 -g 等", en: "Compile flags (default: -O3 -march=native -fopenmp). Examples: -O2, -O0 -g." }
          type: string
          required: false
        }
      ]
    },
    {
      name: run_cpp
      description: { zh: "运行自定义 C++ 代码", en: "Run custom C++ code." }
      parameters: [
        {
          name: script
          description: { zh: "要执行的 C++ 代码内容", en: "C++ source code to execute." }
          type: string
          required: true
        },
        {
          name: compile_flags
          description: { zh: "编译选项，默认为 -O3 -march=native -fopenmp。可自定义如 -O2、-O0 -g 等", en: "Compile flags (default: -O3 -march=native -fopenmp). Examples: -O2, -O0 -g." }
          type: string
          required: false
        }
      ]
    },
    {
      name: run_cpp_file
      description: { zh: "运行 C++ 文件", en: "Run a C++ file." }
      parameters: [
        {
          name: file_path
          description: { zh: "C++ 文件路径", en: "Path to the C++ file." }
          type: string
          required: true
        },
        {
          name: compile_flags
          description: { zh: "编译选项，默认为 -O3 -march=native -fopenmp。可自定义如 -O2、-O0 -g 等", en: "Compile flags (default: -O3 -march=native -fopenmp). Examples: -O2, -O0 -g." }
          type: string
          required: false
        }
      ]
    }
  ]
}*/
"""

        val OPERIT_EDITOR = """
/* METADATA
{
  name: "operit_editor"
  display_name: {
    zh: "Operit平台编辑器"
    en: "Operit Platform Editor"
  }
  description: {
    zh: '''Operit 平台配置直改工具包：提供一组可直接读取与修改 Operit 平台设置的工具，覆盖 MCP、Skill、Sandbox Package、角色卡、功能模型绑定、模型参数、上下文总结与 TTS/STT 语音服务配置。'''
    en: '''Direct Operit platform configuration toolkit: a collection of tools for reading and directly modifying Operit platform settings, covering MCP, Skill, Sandbox Package, character cards, function-model bindings, model parameters, context-summary settings, and TTS/STT speech-service configuration.'''
  }

  enabledByDefault: true

  "category": "Chat",
  tools: [
    {
      name: "operit_editor"
      description: {
        zh: '''配置排查手册。

【触发条件】
- 用户提到 MCP/Skill 安装失败、无法启动、工具不出现、导入失败、重名冲突、配置文件怎么改
- 用户提到沙盒包（Package）开关、内置包列表、导入删除路径、包启用状态异常
- 用户让你排查 Operit 的插件配置路径、部署目录、开关状态、环境变量
- 用户提到功能模型绑定、模型配置新增/删除/修改、模型连接测试
- 用户提到角色卡的新增、编辑、删除、激活、酒馆 JSON 导入或导出
- 用户提到 TTS/STT 语音服务不会配置、参数太多不会填、语音播报/语音识别不可用
- 问题核心是“配置和部署链路”，而不是普通问答

【MCP：安装与排查】
1) 配置目录：/sdcard/Download/Operit/mcp_plugins/
- 主配置：mcp_config.json
- 运行状态缓存：server_status.json（非实时快照，仅用于状态记录与工具缓存，不作为排查判定依据）
2) 两侧路径要严格区分：
- Android 侧是源目录（用户导入/存放目录），不是最终运行目录
- Linux 侧是最终运行目录：~/mcp_plugins/<pluginId最后一段>
- MCP 真正启动时，执行目录与命令都以 Linux 侧为准
3) 本地部署实际行为（代码逻辑）：
- 创建目标目录
- 将 Android 侧插件目录复制到 Linux 侧目录
- 执行自动分析出的安装/构建命令（会跳过启动命令）
3.1) 本地插件识别规则：
- 这样识别是为兼容存储位置外层套目录的情况（如 `<pluginId>/<repo>-main/...`）；Android 侧目录内至少要命中一个标志文件：`README.md`、`package.json`、`mcp.config.json`、`main.js`、`main.py`、`index.js`、`index.py`，否则可能被判定为未安装，进不了启动列表。
4) 命令型插件判定：
- 对于 command 为 npx/uvx/uv 的命令型插件，系统按“已部署”处理，仅做最小目录准备。
- 配置 Node 类命令型 MCP 时，mcp_config.json 里仍应按上游常见写法填写 `command: "npx"`；不要自行改写成 `pnpm` 或 `npm`。
- 软件内部启动这类 `npx` MCP 时，会自动把 `npx` 改写为 `pnpm dlx` 执行，并去掉 `-y`/`--yes` 一类确认参数。
- 因此这类 MCP 的实际运行依赖是 `pnpm`；Linux 终端里必须装有 `pnpm`，不能只装 `npm`。
- 不要把 command 改成 `npm`；当前已知这样可能触发 `double free` 报错。现阶段约定是：配置时按 `npx` 填，运行时由软件内部转成 `pnpm dlx`。
5) 系统启动行为（必须理解）：
- 本地插件：系统会读取 mcp_config.json 中该插件的 command/args/env，使用 cwd=~/mcp_plugins/<shortName> 启动进程；可用性以“工具可调用/服务可响应”为准
- 远程插件：系统按 endpoint + connectionType（可选 bearerToken/headers）发起连接并校验连通
6) command 的实际执行位置（必须按此理解）：
- 本地插件启动时，系统在 Linux 终端环境中启动进程；执行工作目录固定是 ~/mcp_plugins/<shortName>
- mcp_config.json 里填写的 command 就是在这个 Linux 工作目录上下文中被执行，不会在 Android 源目录执行
- args 里的相对路径，统一按该 cwd 解析
6.1) node 命令示例（按插件ID）：
- 例：pluginId=owner/my-plugin，则 shortName=my-plugin，cwd=~/mcp_plugins/my-plugin
- 如果入口文件在 ~/mcp_plugins/my-plugin/dist/index.js，则写：
  "command": "node"
  "args": ["dist/index.js"]
- 这里 args 必须按 cwd 写相对路径，不要写 /sdcard/... 的 Android 路径
7) mcp_config.json 字段规范：
- 顶层必须有 mcpServers（对象）
- mcpServers 的 key 是 serverId（通常与插件ID一致，避免随意改名）
- pluginId（即 mcpServers 的 key）只允许 a-zA-Z_ 和空格
- 每个 server 常用字段：
  - command（必填，启动命令）
  - args（可选，字符串数组）
  - env（可选，键值对）
  - autoApprove（可选，数组）
  - disabled（可选，true=禁用）
- MCP 的环境变量必须写在 mcpServers.<id>.env；`read_environment_variable` / `write_environment_variable` 不会读写这里。
8) mcp_config.json 路径写法规则：
- 不要把 Android 绝对路径写进本地插件启动参数（例如 /sdcard/...）
- 本地插件命令应按 Linux 运行目录编写，优先相对路径（因为 cwd 已固定到 ~/mcp_plugins/<shortName>）
- 如果必须写绝对路径，也应是 Linux 侧路径，不应写 Android 侧路径
9) 启用开关：
- 本地插件使用 mcpServers.<id>.disabled
- 远程插件使用 pluginMetadata.<id>.disabled
10) MCP 排查顺序（按顺序执行）：
- 检查开关是否启用
- 检查本地部署目录是否存在且非空
- 检查 mcp_config.json 的 command/args/env 字段是否完整
- 检查 args 是否误写 Android 路径
- 检查 env 中所需 key/token
- 不要把 server_status.json 的 active 当作唯一依据；优先看工具是否可拉取、可调用
- 检查终端依赖（node/pnpm/python/uv）与 MCP 服务状态；其中 Node 类 `npx` MCP 实际依赖 `pnpm`，若缺少 `pnpm` 将无法启动

【Skill：安装与排查】
1) 目录：/sdcard/Download/Operit/skills/
2) 识别规则：每个 Skill 必须是一个文件夹，且包含 SKILL.md（skill.md 也可）。
3) 添加方式（按这个做）：
- 先从可信来源下载 Skill（zip 或仓库源码均可）
- 把下载内容解压后，直接放到 /sdcard/Download/Operit/skills/
- 最终目录结构必须是 /sdcard/Download/Operit/skills/<skill_name>/，且该目录内有 SKILL.md
4) 元数据解析：
- 优先读取 frontmatter 中的 name/description
- 若缺失，回退读取文件前40行里的 name:/description:
5) AI 可见性：
- 列表开关关闭后，Skill 仍在本地，但 AI 不会使用
6) Skill 排查顺序：
- 先确认路径和 SKILL.md
- 再确认是否重名冲突
- 再确认开关是否开启
- 最后检查 SKILL.md 内容是否完整（步骤/约束/输出）

【Sandbox Package：安装与排查】
1) 沙盒包目录（外部）：
- Android/data/com.ai.assistance.operit/files/packages
2) 内置包：
- 内置包来自应用内置资源，不在上述外部目录；删除内置包文件不是常规操作，通常只做开关管理。
3) 导入与删除：
- 导入：把 `.js` 或 `.toolpkg` 放入/导入到外部 packages 目录。
- 删除：外部包可直接按文件路径删除；删除前先确认是否仍被依赖。
4) 开关管理（优先使用工具）：
- 先调用 list_sandbox_packages 获取“内置+外部”包列表与当前 enabled 状态。
- 再调用 set_sandbox_package_enabled(package_name, enabled) 执行启停。
5) 制作包文档：
- https://cdn.jsdelivr.net/gh/AAswordman/Operit@main/docs/SCRIPT_DEV_SKILL.md
- 该地址可直接通过 HTTP GET 请求访问，用于拉取原始 Markdown 文档内容。
6) 软件内调试烧录：
- 普通 `.js` 沙盒包优先用 `debug_install_js_package`。
- `ToolPkg` 优先用 `debug_install_toolpkg`；它会处理目录/manifest/.toolpkg 的打包或安装，并触发 ToolPkg 的刷新链路。

【Package 兼容模型（重要）】
- AI 看到的 package 是统一抽象，底层可能来自 MCP、Skill、Sandbox Package 任意一种。
- 可用包列表中的条目，不保证同类型；可能是三种类型混合出现。
- `use_package` 是三兼容入口：对 MCP/Skill/Sandbox Package 都可统一调用。
- `ping_mcp` 工具是 `use_package` 的直通封装，用于快速探测指定包是否可被加载。

【市场 Agent API（HTTP，只读）】
- 基础前缀：`https://api.operit.app/market-stats`
- 搜索：`/agent/search?q=<关键词>&type=mcp|skill|package|script&limit=10`
- 详情：`/agent/items/<type>/<id>`
- 安装计划：`/agent/items/<type>/<id>/install-plan`
- `package` / `script` 的 install_plan 通常会返回 `download_url`、`tracked_download_url`、`sha256`、`runtime_package_id`。
- `skill` 的 install_plan 通常会返回 `repository_url`。
- `mcp` 的 install_plan 可能返回 `config`（可直接作为 installConfig 参考）或 `repository_url`。
- 当前软件未对 JS 暴露统一的一键安装市场接口；需要安装时，按条目类型自行下载、解压、导入，必要时配合 `debug_install_js_package` / `debug_install_toolpkg` / `use_package`。

【功能模型与模型配置】
1) 模型配置（Model Config）：
- 每个模型配置是一套完整连接参数（provider / endpoint / api key / model_name / custom_headers / 各能力开关）。
- 可以新增、删除、修改；删除默认配置 `default` 是禁止的。
2) 功能模型（Function Model）：
- 每个功能类型（如 CHAT/SUMMARY/TRANSLATION 等）会绑定到一个模型配置。
- 当一个配置里 `model_name` 写了多个模型（逗号分隔），还要指定 `model_index` 选择第几个。
3) 关键工具（优先使用）：
- `list_model_configs`：查看全部模型配置 + 当前功能绑定。
- `create_model_config`：新增模型配置（可带初始 provider/endpoint/key/model_name/custom_headers）。
- `update_model_config`：修改已有配置（按 config_id）。
- `delete_model_config`：删除配置（默认配置不可删）。
- `list_function_model_configs`：仅列出功能 -> 配置绑定关系（轻量）。
- `get_function_model_config`：查看某个功能当前绑定的单个配置详情。
- `set_function_model_config`：为功能指定配置与模型索引。
- `test_model_config_connection`：按设置页同等逻辑测试配置连通与多模态能力。
4) 配置修改后：
- 若该配置被某些功能使用，系统会刷新对应功能服务；绑定变更也会刷新目标功能服务。
5) 用户抱怨“输出总被截断”时：
- 可先用 `get_function_model_config` 查看对应功能绑定配置里的 `max_tokens` 参数。
- 对 DeepSeek 来说，默认常见是 4096；可将 `max_tokens_enabled` 打开并把 `max_tokens` 设到 8192 再测试。
- 对其他模型，先联网确认该模型可支持的输出上限后再设置。

【角色卡管理】
1) 角色卡是全局配置资产。创建、编辑角色设定、模型绑定、记忆配置、工具白名单、激活与 Tavern JSON 导入导出均使用本包的角色卡工具。
2) 对话只在创建或发送时引用角色卡；不要把角色卡完整配置管理放进会话操作。
3) 关键工具：
- `list_character_cards`：查看完整角色卡列表和当前活跃角色卡。
- `get_character_card`：读取单张角色卡完整配置。
- `create_character_card`、`update_character_card`、`delete_character_card`：管理角色卡。
- `set_active_character_card`、`clear_active_character_card`：管理活跃角色卡。
- `import_character_card_from_tavern_json`、`export_character_card_to_tavern_json`：与 Tavern JSON 交换单张角色卡。
4) `attached_tag_ids` 与四个 `allowed_*` 字段都使用 JSON 字符串数组，例如 `["tag-a","tag-b"]`。
5) 默认角色卡不可删除。更新不会改变角色卡 ID、创建时间或默认属性。

【上下文总结模块（Context Summary）】
1) 用途：
- 控制会话上下文窗口与“何时触发总结”，用于降低上下文膨胀导致的丢信息、跑偏或响应不稳定。
- 只有当前对话功能模型（CHAT）所绑定配置里的上下文总结参数，会在实际对话中生效。
2) 核心机制说明：
- 软件内有一个 max 开关，即 `enable_max_context_mode`。
- 开启时使用 `max_context_length`，关闭时使用 `context_length`，目标是为用户节约 token，并按场景动态决定使用长度。
- `enable_summary` 控制是否自动总结；当上下文超过 `summary_token_threshold * 当前可用上下文长度` 时，会触发总结。
3) 建议排查顺序：
- 先用 `get_context_summary_config` 看当前功能绑定配置的上下文总结参数。
- 再用 `set_context_summary_config` 设置上下文总结参数（可传入参数覆盖默认值）。
- 若仍异常，再结合具体模型能力与业务负载做细调。

【TTS/STT 语音服务配置】
1) 配置入口：
- 在软件设置里的 Speech Services（语音服务）页面配置。
- 该页面会自动保存；改完后语音服务实例会自动重建。
2) TTS（文本转语音）可选引擎：
- `SIMPLE_TTS`：系统 TTS，基本无需填网络参数。
- `HTTP_TTS`：需重点填写 `url_template`、`headers`、`http_method`、`content_type`、`request_body`；若服务先返回 JSON / 字段 / 下载链接，再额外填写 `response_pipeline`。
- `OPENAI_WS_TTS`：需填写 `url_template`、`api_key`、`model_name`、`voice_id`。其中 `url_template` 应为 Realtime WebSocket 地址（例如 `wss://api.openai.com/v1/realtime`）。
- `SILICONFLOW_TTS`：需填写 `api_key`、`model_name`、`voice_id`。
- `MINIMAX_TTS`：需填写 `api_key`，可选填写 `url_template`、`model_name`、`voice_id`。默认接口为 `https://api.minimaxi.com/v1/t2a_v2`，内部固定按 `data.audio -> http_get` 解析音频。
- `MIMO_TTS`：需填写 `api_key`，可选填写 `url_template`、`model_name`、`voice_id`。预置音色使用 `mimo-v2.5-tts` 和短 `voice_id`；声音克隆使用 `mimo-v2.5-tts-voiceclone`，`voice_id` 填完整 `data:audio/...;base64,...` 音频样本。默认接口为 `https://api.xiaomimimo.com/v1/chat/completions`，内部固定按 `choices[0].message.audio.data -> base64_decode` 解析音频。
- `DOUBAO_TTS`：豆包 TTS，需填写 `url_template`、`api_key`（Token）、`model_name`（App ID）、`voice_id`（voice_type）。默认接口为 `https://openspeech.bytedance.com/api/v1/tts`，继承 HTTP TTS 队列和响应管线，内部固定按 `data -> base64_decode` 解析音频。
- `OPENAI_TTS`：需填写 `url_template`、`api_key`、`model_name`、`voice_id`。
- `VITS_TTS`：本地 VITS/Piper TTS。`tts_vits_package_path` 填本地模型包 `.zip` 或已解压目录，`tts_vits_speaker_id` 可选填数字 speaker id，`tts_vits_options` 可选填写 `sample_rate`、`threads`、`noise_scale`、`length_scale`、`noise_w`、`frontend`、`text_mode`、`speaker_count`、输入名和 blank/bos/eos token 等本地参数。
3) STT（语音转文本）可选引擎：
- `SHERPA_NCNN`：本地识别，通常无需 API Key。
- `OPENAI_STT`：需填写 `endpoint_url`、`api_key`、`model_name`。
- `DEEPGRAM_STT`：需填写 `endpoint_url`、`api_key`、`model_name`。
4) 最常见填错点（优先检查）：
- `HTTP_TTS` 的 `headers` 不是合法 JSON（必须是对象）。
- `HTTP_TTS` 的模板没放 `{text}` 占位符（GET 通常在 URL，POST 通常在 body）。
- `HTTP_TTS` 的 `response_pipeline` 不是合法 JSON 数组，或步骤名 / `path` 填错。
- `OPENAI_WS_TTS` 把 HTTP 地址填成了 WebSocket 地址，或把 WebSocket 地址误填成 HTTP 地址。
- `VITS_TTS` 的 `tts_vits_package_path` 不是本地 `.zip` 模型包或已解压目录，或文件不存在。
- `VITS_TTS` 模型包里没有可识别的 `.onnx` / config JSON / lexicon，或配置里缺少 `sample_rate` / token 映射。
- `VITS_TTS` 的 `tts_vits_options` 不是合法 JSON（必须是对象），或把本地参数名 / 数值类型写错。
- TTS/STT 的 endpoint 路径写错（比如把 chat/completions 写成 audio 接口）。
- `model_name` 填了不存在的模型或与接口不匹配。
- 改完配置后没有重新测试语音播报或语音识别。
5) HTTP_TTS 占位符说明（按代码逻辑）：
- 必填占位符：`{text}`。
  - 当 `http_method=GET` 时，`{text}` 必须在 `url_template` 里。
  - 当 `http_method=POST` 时，`{text}` 必须在 `request_body` 里。
- 可选占位符：`{rate}`、`{pitch}`、`{voice}`。
- 当前对外可稳定使用的占位符：`{text}`、`{rate}`、`{pitch}`、`{voice}`、`{apiKey}`、`{model}`、`{locale}`、`{uuid}`。
6) HTTP_TTS 响应处理说明（已发布版本兼容）：
- `response_pipeline` 留空或传 `[]`：保持旧行为，直接把首个响应体当音频。
- 当服务端先返回 JSON、字段或下载链接时，再填写 `response_pipeline`，按步骤解析。
- 当前可用步骤：`parse_json`、`pick`、`parse_json_string`、`http_get`、`http_request_from_object`、`base64_decode`。
- 常见 JSON 下载链接场景：
  - `response_pipeline`: `[{"type":"parse_json"},{"type":"pick","path":"audio_uri"},{"type":"http_get"}]`
- 若字段里还是 JSON 字符串：
  - `response_pipeline`: `[{"type":"parse_json"},{"type":"pick","path":"data.payload"},{"type":"parse_json_string"},{"type":"pick","path":"audio.url"},{"type":"http_get"}]`
7) 可直接参考的最小模板：
- HTTP TTS（GET）：
  - `url_template`: `https://example.com/tts?text={text}`
  - `headers`: `{}`
  - `http_method`: `GET`
  - `content_type`: `application/json`
- HTTP TTS（POST）：
  - `url_template`: `https://example.com/tts`
  - `headers`: `{"Authorization":"Bearer <API_KEY>"}`
  - `http_method`: `POST`
  - `content_type`: `application/json`
  - `request_body`: `{"text":"{text}"}`
- OpenAI STT（默认常见）：
  - `endpoint_url`: `https://api.openai.com/v1/audio/transcriptions`
  - `model_name`: `whisper-1`
8) 排查顺序（建议）：
- 先确认选中的引擎类型是否正确（TTS 与 STT 分开看）。
- 再检查 endpoint / key / model 三件套是否完整。
- 再检查 HTTP 模板字段（headers JSON、method、body、占位符、response_pipeline）。
- 至少做一次真实 TTS 播报测试；若还要排查 STT，再另外走语音识别链路。
9) 对应工具（可直接用）：
- `get_speech_services_config`：获取当前 TTS/STT 配置快照（含引擎类型与关键字段）。
- `set_speech_services_config`：按字段修改 TTS/STT 配置（支持只改部分字段）。
- `test_tts_playback`：按当前 TTS 配置播放一次测试文本（支持临时覆盖语速/音调）。

【多模态输入规则】
1) 能力开关含义：
- 模型配置里的“支持 Tool Call / 识图 / 音频 / 视频”等开关，只是软件侧能力标识，不等于模型真实能力。
- 实际配置时，必须依据模型真实支持情况来开关，不能乱开。
2) 软件识图主链路：
- 当“对话功能模型”的模型配置开启识图且模型真实支持时：聊天附图会直接发给该模型识别。
- 当对话模型不支持识图时：软件会尝试走 OCR，或走“识图功能模型”进行识图中转。
3) 用户有识图需求时的可行条件：
- 条件 A：对话模型支持识图。
- 条件 B：对话模型不支持识图，但识图功能模型支持识图。
- 若识图功能模型也不支持识图：最终回退到 OCR。

【绘图输出说明】
- 绘图通过工具包实现。
- 软件内置了一些绘图包，可调用 list_sandbox_packages 查看。
- 通常只需启用其中一个可用绘图包即可，无需全部开启。

【执行原则】
- 严格按用户明确指示执行，不自行定义“问题”或追加未被要求的目标。
- 任何会改动用户配置的操作（开关、导入/删除、写环境变量、模型配置增删改、重启）都必须先得到用户明确确认。
- 用户没有明确要求执行某个工具时，不主动调用写入类工具。
- 回答优先基于本手册的路径与规则，避免泛化推断。'''
        en: '''Configuration troubleshooting guide.

[Trigger conditions]
- The user mentions MCP/Skill install failure, startup failure, tools not appearing, import failure, duplicate name conflicts, or config editing
- The user mentions sandbox package toggles, built-in package listing, import/delete paths, or package enable-state issues
- The user asks to troubleshoot plugin config paths, deploy directories, enable switches, or environment variables
- The user mentions function model bindings, adding/deleting/updating model configs, or testing model connectivity
- The user says TTS/STT setup is confusing, too many fields to fill, or speech playback/recognition is not working
- The core issue is configuration/deployment flow rather than normal Q&A

[MCP: install and troubleshooting]
1) Config directory: /sdcard/Download/Operit/mcp_plugins/
- Main config: mcp_config.json
- Runtime status cache: server_status.json (non-realtime snapshot for status/tool cache only; not a troubleshooting source of truth)
2) Keep Android-side and Linux-side paths strictly separated:
- Android side is the source/import location, not the final runtime location
- Linux runtime directory is: ~/mcp_plugins/<last-segment-of-pluginId>
- Actual MCP startup always runs from the Linux side
3) Real deployment behavior (from implementation):
- Create target directory
- Copy plugin files from Android side to Linux side
- Execute auto-generated install/build commands (startup commands are skipped)
3.1) Local plugin recognition rule:
- This exists to handle nested storage layouts (for example `<pluginId>/<repo>-main/...`): the Android-side plugin directory must contain at least one marker file such as `README.md`, `package.json`, `mcp.config.json`, `main.js`, `main.py`, `index.js`, or `index.py`; otherwise it may be treated as not installed and never enter the startup list.
4) Command-based plugin handling:
- For command-based plugins using npx/uvx/uv, the system treats them as deployed and only performs minimal directory preparation.
- For Node-style command MCPs, keep the config in mcp_config.json aligned with upstream examples and still write `command: "npx"`; do not rewrite it to `pnpm` or `npm` yourself.
- When the app starts this kind of `npx` MCP, it internally rewrites `npx` to `pnpm dlx` and strips confirmation flags such as `-y` / `--yes`.
- That means the real runtime dependency for this kind of MCP is `pnpm`; `pnpm` must exist in the Linux terminal, and having only `npm` is not enough.
- Do not change the command to `npm`; this is known to trigger `double free` errors. The current convention is: configure it as `npx`, and let the app run it internally as `pnpm dlx`.
5) System startup behavior (critical):
- Local plugins: the app reads command/args/env from mcp_config.json and starts the process with cwd=~/mcp_plugins/<shortName>; availability should be judged by real tool call/response
- Remote plugins: the app connects using endpoint + connectionType (optional bearerToken/headers) and verifies connectivity
6) Actual execution location of command (must be understood this way):
- For local plugins, the process starts in the Linux terminal environment with fixed working directory: ~/mcp_plugins/<shortName>
- The command from mcp_config.json is executed in that Linux working-directory context, not in the Android source directory
- Any relative paths in args are resolved against that cwd
6.1) node command example (by plugin ID):
- Example: pluginId=owner/my-plugin, so shortName=my-plugin and cwd=~/mcp_plugins/my-plugin
- If the entry file is ~/mcp_plugins/my-plugin/dist/index.js, write:
  "command": "node"
  "args": ["dist/index.js"]
- args must be relative to cwd; do not use Android paths such as /sdcard/...
7) mcp_config.json field rules:
- Top level must contain mcpServers (object)
- Each key in mcpServers is a serverId (normally keep it aligned with plugin ID)
- pluginId (the mcpServers key) only allows letters a-zA-Z, underscore (_), and spaces
- Common server fields:
  - command (required, startup command)
  - args (optional, string array)
  - env (optional, key-value map)
  - autoApprove (optional, array)
  - disabled (optional, true means disabled)
- MCP environment variables must be configured in mcpServers.<id>.env; `read_environment_variable` / `write_environment_variable` do not read or write these MCP env entries.
8) Path-writing rules in mcp_config.json:
- Do not put Android absolute paths (for example /sdcard/...) in local plugin startup args
- Write local plugin command/args for Linux runtime; prefer relative paths because cwd is fixed to ~/mcp_plugins/<shortName>
- If an absolute path is required, it must be a Linux path, not an Android path
9) Enable switch:
- Local plugin uses mcpServers.<id>.disabled
- Remote plugin uses pluginMetadata.<id>.disabled
10) MCP troubleshooting order:
- Check enable switch
- Check local deployed directory exists and is non-empty
- Check whether command/args/env in mcp_config.json are complete
- Check whether args incorrectly use Android paths
- Check required key/token in env
- Do not treat `active` in server_status.json as the single source of truth; prioritize whether tools can be fetched/called successfully
- Check terminal dependencies (node/pnpm/python/uv) and MCP service status; Node-style `npx` MCPs actually depend on `pnpm`, so missing `pnpm` will prevent startup

[Skill: install and troubleshooting]
1) Directory: /sdcard/Download/Operit/skills/
2) Recognition rule: each Skill must be a folder containing SKILL.md (skill.md is also accepted).
3) How to add a skill (use this workflow):
- Download the skill from a trusted source (zip or repository source code).
- Extract it, then place the folder directly under /sdcard/Download/Operit/skills/
- Final structure must be /sdcard/Download/Operit/skills/<skill_name>/ and that folder must contain SKILL.md
4) Metadata parsing:
- Prefer frontmatter name/description
- Fallback to name:/description: in the first 40 lines
5) AI visibility:
- If the list switch is off, the Skill remains local but is hidden from AI usage
6) Skill troubleshooting order:
- Verify path and SKILL.md
- Check duplicate-name conflict
- Check enable switch
- Check whether SKILL.md instructions are complete (steps/constraints/outputs)

[Sandbox Package: install and troubleshooting]
1) External sandbox packages directory:
- Android/data/com.ai.assistance.operit/files/packages
2) Built-in packages:
- Built-in packages come from app bundled assets, not from the external directory above; usually manage via enable/disable instead of file deletion.
3) Import and delete:
- Import: place/import `.js` or `.toolpkg` into the external packages directory.
- Delete: for external packages, delete by file path after confirming dependency impact.
4) Toggle management (prefer tools):
- Call list_sandbox_packages first to get built-in + external package list and current enabled state.
- Then call set_sandbox_package_enabled(package_name, enabled) to apply changes.
5) Package authoring guide:
- https://cdn.jsdelivr.net/gh/AAswordman/Operit@main/docs/SCRIPT_DEV_SKILL.md
- This URL can be accessed directly with an HTTP GET request to fetch the raw Markdown document.
6) In-app debug install:
- For plain `.js` sandbox packages, prefer `debug_install_js_package`.
- For `ToolPkg`, prefer `debug_install_toolpkg`; it handles packaging/install flow for folder/manifest/.toolpkg sources and triggers the ToolPkg refresh path.

[Package compatibility model (important)]
- The package list seen by AI is a unified abstraction, and each item may come from MCP, Skill, or Sandbox Package.
- Available package entries are not guaranteed to be a single type; mixed types are expected.
- `use_package` is tri-compatible and can be called uniformly for MCP/Skill/Sandbox Package.
- `ping_mcp` is a thin wrapper over `use_package` for quick package availability probing.

[Market agent API (HTTP, read-only)]
- Base prefix: `https://api.operit.app/market-stats`
- Search: `/agent/search?q=<query>&type=mcp|skill|package|script&limit=10`
- Detail: `/agent/items/<type>/<id>`
- Install plan: `/agent/items/<type>/<id>/install-plan`
- `package` / `script` install_plan usually returns `download_url`, `tracked_download_url`, `sha256`, and `runtime_package_id`.
- `skill` install_plan usually returns `repository_url`.
- `mcp` install_plan may return `config` (usable as installConfig reference) or `repository_url`.
- The app does not currently expose a unified one-click market install API to JS; when installation is needed, download/extract/import by item type and use `debug_install_js_package`, `debug_install_toolpkg`, or `use_package` when appropriate.

[Function model and model config]
1) Model config:
- Each model config is one full connection profile (provider / endpoint / api key / model_name / custom_headers / capability switches).
- Configs can be created, updated, and deleted; deleting the default `default` config is forbidden.
2) Function model binding:
- Each function type (for example CHAT/SUMMARY/TRANSLATION) is bound to one model config.
- If `model_name` contains multiple models (comma-separated), `model_index` selects which one to use.
3) Key tools (prefer these):
- `list_model_configs`: list all model configs and current function bindings.
- `create_model_config`: create a new model config (with optional initial provider/endpoint/key/model_name/custom_headers).
- `update_model_config`: update an existing config by config_id.
- `delete_model_config`: delete a config (default cannot be deleted).
- `list_function_model_configs`: list function -> config bindings only (lightweight).
- `get_function_model_config`: get one bound config detail by function type.
- `set_function_model_config`: assign config and model index for a function.
- `test_model_config_connection`: run settings-UI-equivalent connectivity/capability checks for a config.
4) After config changes:
- If a config is used by functions, corresponding function services are refreshed; binding updates also refresh target function service.
5) When users complain about truncated outputs:
- Use `get_function_model_config` to inspect `max_tokens` in the bound config for that function.
- For DeepSeek, a common default is 4096; enable `max_tokens_enabled` and try setting `max_tokens` to 8192.
- For other models, verify the supported output-token limit online before changing values.

[Context summary module]
1) Purpose:
- Controls context window behavior and summary-trigger conditions to reduce context bloat, drift, and unstable long-chat responses.
- Only context-summary settings on the config currently bound to CHAT are effective in real conversation.
2) Core mechanism:
- There is a max switch in the app: `enable_max_context_mode`.
- When enabled, it uses `max_context_length`; when disabled, it uses `context_length`, so context length can be chosen dynamically to save tokens.
- `enable_summary` controls automatic summarization. When context exceeds `summary_token_threshold * current available context length`, summarization is triggered.
3) Recommended troubleshooting flow:
- Use `get_context_summary_config` to inspect current context-summary fields for a function.
- Use `set_context_summary_config` to set context-summary fields (you can override default values via params).
- If issues remain, fine-tune based on real model capability and workload.

[TTS/STT speech-service configuration]
1) Where to configure:
- Configure it on the Speech Services page in app settings.
- The page auto-saves; after changes, speech-service instances are rebuilt automatically.
2) TTS (text-to-speech) engines:
- `SIMPLE_TTS`: system TTS, usually no network fields required.
- `HTTP_TTS`: mainly fill `url_template`, `headers`, `http_method`, `content_type`, `request_body`; if the service first returns JSON / fields / a download link, also fill `response_pipeline`.
- `OPENAI_WS_TTS`: fill `url_template`, `api_key`, `model_name`, `voice_id`. `url_template` should be a Realtime WebSocket endpoint such as `wss://api.openai.com/v1/realtime`.
- `SILICONFLOW_TTS`: fill `api_key`, `model_name`, `voice_id`.
- `MINIMAX_TTS`: fill `api_key`; optionally set `url_template`, `model_name`, and `voice_id`. Default endpoint is `https://api.minimaxi.com/v1/t2a_v2`, and audio is resolved from `data.audio` automatically.
- `MIMO_TTS`: fill `api_key`; optionally set `url_template`, `model_name`, and `voice_id`. Use `mimo-v2.5-tts` with a short `voice_id` for preset voices. Use `mimo-v2.5-tts-voiceclone` with a full `data:audio/...;base64,...` audio sample in `voice_id` for voice cloning. Default endpoint is `https://api.xiaomimimo.com/v1/chat/completions`, and audio is resolved from `choices[0].message.audio.data` with Base64 decoding.
- `DOUBAO_TTS`: Doubao TTS. Fill `url_template`, `api_key` (token), `model_name` (App ID), and `voice_id` (voice_type). Default endpoint is `https://openspeech.bytedance.com/api/v1/tts`; it inherits the HTTP TTS queue and response pipeline and resolves audio from `data` with Base64 decoding.
- `OPENAI_TTS`: fill `url_template`, `api_key`, `model_name`, `voice_id`.
- `VITS_TTS`: local VITS/Piper TTS. Set `tts_vits_package_path` to the local model package `.zip` or extracted package directory, optionally set `tts_vits_speaker_id` to a numeric speaker id, and use `tts_vits_options` for local options such as `sample_rate`, `threads`, `noise_scale`, `length_scale`, `noise_w`, `frontend`, `text_mode`, `speaker_count`, input names, and blank/bos/eos token settings.
3) STT (speech-to-text) engines:
- `SHERPA_NCNN`: local recognition, usually no API key required.
- `OPENAI_STT`: fill `endpoint_url`, `api_key`, `model_name`.
- `DEEPGRAM_STT`: fill `endpoint_url`, `api_key`, `model_name`.
4) Most common mistakes (check first):
- `headers` in `HTTP_TTS` is not valid JSON (must be an object).
- Missing `{text}` placeholder in HTTP TTS template (typically in URL for GET, in body for POST).
- `response_pipeline` in `HTTP_TTS` is not a valid JSON array, or a step name / `path` is incorrect.
- `OPENAI_WS_TTS` is configured with an HTTP URL instead of a WebSocket URL, or vice versa.
- `tts_vits_package_path` in `VITS_TTS` is not a local `.zip` model package or extracted package directory, or it does not exist.
- The `VITS_TTS` package has no recognizable `.onnx` / config JSON / lexicon, or the config is missing `sample_rate` / token mappings.
- `tts_vits_options` in `VITS_TTS` is not valid JSON, or local option names / numeric values are invalid.
- Wrong endpoint path for TTS/STT (for example using chat/completions instead of audio endpoints).
- `model_name` does not exist or does not match the API.
- No real retest after saving config.
5) HTTP_TTS placeholder rules (from implementation):
- Required placeholder: `{text}`.
  - When `http_method=GET`, `{text}` must appear in `url_template`.
  - When `http_method=POST`, `{text}` must appear in `request_body`.
- Optional placeholders: `{rate}`, `{pitch}`, `{voice}`.
- Stable placeholders for external configuration: `{text}`, `{rate}`, `{pitch}`, `{voice}`, `{apiKey}`, `{model}`, `{locale}`, `{uuid}`.
6) HTTP_TTS response handling notes (forward-compatible with released configs):
- Leave `response_pipeline` empty or use `[]` to keep the old behavior: the first response body is treated as audio directly.
- Only fill `response_pipeline` when the service returns JSON, nested fields, or a follow-up download URL before audio is available.
- Currently supported steps: `parse_json`, `pick`, `parse_json_string`, `http_get`, `http_request_from_object`, `base64_decode`.
- Common JSON download-link case:
  - `response_pipeline`: `[{"type":"parse_json"},{"type":"pick","path":"audio_uri"},{"type":"http_get"}]`
- If the picked field is itself a JSON string:
  - `response_pipeline`: `[{"type":"parse_json"},{"type":"pick","path":"data.payload"},{"type":"parse_json_string"},{"type":"pick","path":"audio.url"},{"type":"http_get"}]`
7) Minimal templates you can copy:
- HTTP TTS (GET):
  - `url_template`: `https://example.com/tts?text={text}`
  - `headers`: `{}`
  - `http_method`: `GET`
  - `content_type`: `application/json`
- HTTP TTS (POST):
  - `url_template`: `https://example.com/tts`
  - `headers`: `{"Authorization":"Bearer <API_KEY>"}`
  - `http_method`: `POST`
  - `content_type`: `application/json`
  - `request_body`: `{"text":"{text}"}`
- OpenAI STT (common default):
  - `endpoint_url`: `https://api.openai.com/v1/audio/transcriptions`
  - `model_name`: `whisper-1`
8) Recommended troubleshooting order:
- Confirm the selected engine type first (TTS and STT separately).
- Check endpoint/key/model as a bundle.
- Then verify HTTP template fields (headers JSON, method, body, placeholder, response_pipeline).
- Run at least one real TTS playback test; if STT also needs troubleshooting, verify recognition in a separate speech flow.
9) Related tools:
- `get_speech_services_config`: fetch current TTS/STT config snapshot (engine types + key fields).
- `set_speech_services_config`: update TTS/STT config fields (partial update supported).
- `test_tts_playback`: play one test utterance with the current TTS config (supports temporary rate/pitch overrides).

[Multimodal input rules]
1) Meaning of capability switches:
- Switches like Tool Call / image / audio / video in model config are software-side capability markers, not proof of real model capability.
- Configure these switches according to actual model support; do not enable blindly.
2) Image understanding main path in app:
- If the chat-function model config enables image understanding and the model truly supports it, attached images are sent directly to that chat model.
- If the chat model does not support image understanding, the app will try OCR, or use the dedicated image-recognition function model as a relay.
3) Valid conditions when users need image understanding:
- Condition A: chat model supports image understanding.
- Condition B: chat model does not support it, but image-recognition function model supports it.
- If the image-recognition model also does not support it, the final fallback is OCR.

[Drawing output note]
- Drawing is implemented via package tools.
- The app includes several built-in drawing packages; use list_sandbox_packages to inspect them.
- Usually enabling one available drawing package is enough; no need to enable all of them.

[Execution principles]
- Follow the user's explicit instructions strictly; do not define your own "problem" or add unrequested goals.
- Any configuration-changing action (toggle/import/delete/write env/model config CRUD/restart) requires explicit user confirmation first.
- If the user did not explicitly ask to execute a specific tool, do not proactively run write-type tools.
- Answer with concrete paths/rules from this guide and avoid generic assumptions.'''
      }
      parameters: []
      advice: true
    },
    {
      name: "how_make_skill"
      description: {
        zh: '''返回如何制作 skill 的双语说明。'''
        en: '''Return a bilingual guide for creating a skill.'''
      }
      parameters: []
    },
    {
      name: "list_sandbox_packages"
      description: {
        zh: '''获取沙盒包列表（内置+外部）及当前启用状态、管理路径。'''
        en: '''Get sandbox package list (built-in + external), current enabled states, and management paths.'''
      }
      parameters: []
    },
    {
      name: "set_sandbox_package_enabled"
      description: {
        zh: '''设置沙盒包开关状态。'''
        en: '''Set sandbox package enabled state.'''
      }
      parameters: [
        {
          name: "package_name"
          description: {
            zh: "沙盒包名称"
            en: "Sandbox package name"
          }
          type: string
          required: true
        },
        {
          name: "enabled"
          description: {
            zh: "是否启用（true/false）"
            en: "Enable state (true/false)"
          }
          type: boolean
          required: true
        }
      ]
    },
    {
      name: "debug_install_js_package"
      description: {
        zh: '''将 Android 侧的普通 `.js` 沙盒包直接烧录到外部 packages 目录，并刷新、启用、重新加载，便于在软件内调试。'''
        en: '''Install an Android-side plain `.js` sandbox package into the external packages directory, refresh it, enable it, and reload it for in-app debugging.'''
      }
      parameters: [
        {
          name: "source_path"
          description: {
            zh: "Android 侧 `.js` 源文件路径"
            en: "Android-side `.js` source file path"
          }
          type: string
          required: true
        },
        {
          name: "enable_after_install"
          description: {
            zh: "安装后是否自动启用，默认 true"
            en: "Whether to enable it automatically after install, default true"
          }
          type: boolean
          required: false
        },
        {
          name: "activate_after_install"
          description: {
            zh: "安装后是否自动 use_package 重新加载，默认 true"
            en: "Whether to automatically call use_package after install, default true"
          }
          type: boolean
          required: false
        }
      ]
    },
    {
      name: "debug_install_toolpkg"
      description: {
        zh: '''根据 Android 侧的 ToolPkg 目录、manifest 或现成 `.toolpkg`，直接打包/烧录到外部 packages 目录，并触发 ToolPkg 安装与刷新链路。'''
        en: '''Package or install an Android-side ToolPkg folder, manifest, or existing `.toolpkg` into the external packages directory and trigger the ToolPkg install/refresh flow.'''
      }
      parameters: [
        {
          name: "source_path"
          description: {
            zh: "Android 侧 ToolPkg 目录、manifest.json/manifest.hjson 或 `.toolpkg` 路径"
            en: "Android-side ToolPkg folder, manifest.json/manifest.hjson, or `.toolpkg` path"
          }
          type: string
          required: true
        },
        {
          name: "reset_subpackage_states"
          description: {
            zh: "是否按 manifest 默认值重置子包启用状态，默认 true"
            en: "Whether to reset subpackage enable states from manifest defaults, default true"
          }
          type: boolean
          required: false
        },
        {
          name: "activate_subpackages"
          description: {
            zh: "可选，逗号或换行分隔的子包 ID；安装后会自动启用并 use_package"
            en: "Optional comma/newline separated subpackage IDs; they will be enabled and activated after install"
          }
          type: string
          required: false
        },
        {
          name: "wait_ms"
          description: {
            zh: "安装广播后等待并轮询刷新的毫秒数，默认 1500"
            en: "Milliseconds to wait and poll for refresh after sending the install broadcast, default 1500"
          }
          type: integer
          required: false
        }
      ]
    },
    {
      name: "debug_run_sandbox_script"
      description: {
        zh: '''直接运行一段 sandbox script。可传 Android 侧 `source_path`，也可直接传 `source_code` 内联代码；会返回结构化执行结果与日志事件。'''
        en: '''Run a sandbox script directly. Accepts either an Android-side `source_path` or inline `source_code`, and returns structured execution results with log events.'''
      }
      parameters: [
        {
          name: "source_path"
          description: {
            zh: "Android 侧脚本文件路径；与 source_code 二选一"
            en: "Android-side script file path; use either this or source_code"
          }
          type: string
          required: false
        },
        {
          name: "source_code"
          description: {
            zh: "直接执行的内联 JavaScript 代码；与 source_path 二选一"
            en: "Inline JavaScript code to execute directly; use either this or source_path"
          }
          type: string
          required: false
        },
        {
          name: "params_json"
          description: {
            zh: "传给脚本运行时的 JSON 参数字符串，默认 {}"
            en: "JSON parameter string passed to the script runtime, default {}"
          }
          type: string
          required: false
        },
        {
          name: "env_file_path"
          description: {
            zh: "可选，Android 侧 env 文件路径"
            en: "Optional Android-side env file path"
          }
          type: string
          required: false
        },
        {
          name: "script_label"
          description: {
            zh: "可选，仅用于内联代码模式下生成结果文件名和显示标识"
            en: "Optional label used only for inline-code mode to name the result file and display path"
          }
          type: string
          required: false
        },
        {
          name: "wait_ms"
          description: {
            zh: "等待结构化结果文件的毫秒数，默认 15000"
            en: "Milliseconds to wait for the structured result file, default 15000"
          }
          type: integer
          required: false
        }
      ]
    },
    {
      name: "read_environment_variable"
      description: {
        zh: '''读取指定环境变量当前值（仅用于沙盒包脚本环境变量排查，不用于 MCP 配置）。'''
        en: '''Read current value of a specified environment variable (sandbox-package script env troubleshooting only, not MCP config env).'''
      }
      parameters: [
        {
          name: "key"
          description: {
            zh: "环境变量名"
            en: "Environment variable key"
          }
          type: string
          required: true
        }
      ]
    },
    {
      name: "write_environment_variable"
      description: {
        zh: '''写入指定环境变量；value 为空时会清除该变量（仅用于沙盒包脚本环境变量，不用于 MCP 配置 env）。'''
        en: '''Write a specified environment variable; empty value clears it (sandbox-package script env only, not MCP config env).'''
      }
      parameters: [
        {
          name: "key"
          description: {
            zh: "环境变量名"
            en: "Environment variable key"
          }
          type: string
          required: true
        },
        {
          name: "value"
          description: {
            zh: "变量值；为空时清除该变量"
            en: "Variable value; empty clears the variable"
          }
          type: string
          required: false
        }
      ]
    },
    {
      name: "restart_mcp_with_logs"
      description: {
        zh: '''触发一次 MCP 重启流程，返回每个插件的启动日志与状态摘要。'''
        en: '''Trigger one MCP restart flow and return per-plugin startup logs with status summary.'''
      }
      parameters: [
        {
          name: "timeout_ms"
          description: {
            zh: "可选，最大等待时长（毫秒）"
            en: "Optional max wait time in milliseconds"
          }
          type: integer
          required: false
        }
      ]
    },
    {
      name: "get_speech_services_config"
      description: {
        zh: '''获取当前 TTS/STT 语音服务配置快照。'''
        en: '''Get current TTS/STT speech services config snapshot.'''
      }
      parameters: []
    },
    {
      name: "set_speech_services_config"
      description: {
        zh: '''按字段更新 TTS/STT 语音服务配置（支持部分字段更新）。'''
        en: '''Update TTS/STT speech services config by fields (partial update supported).'''
      }
      parameters: [
        {
          name: "tts_service_type"
          description: {
            zh: "可选，SIMPLE_TTS/HTTP_TTS/OPENAI_WS_TTS/SILICONFLOW_TTS/MINIMAX_TTS/MIMO_TTS/DOUBAO_TTS/OPENAI_TTS/VITS_TTS"
            en: "Optional, SIMPLE_TTS/HTTP_TTS/OPENAI_WS_TTS/SILICONFLOW_TTS/MINIMAX_TTS/MIMO_TTS/DOUBAO_TTS/OPENAI_TTS/VITS_TTS"
          }
          type: string
          required: false
        },
        {
          name: "tts_url_template"
          description: {
            zh: "可选，HTTP 类 TTS 的 URL 模板。HTTP 系列仅支持 `{text}`、`{rate}`、`{pitch}`、`{voice}`"
            en: "Optional URL template for HTTP-style TTS providers. HTTP-style providers support only `{text}`, `{rate}`, `{pitch}`, `{voice}`"
          }
          type: string
          required: false
        },
        {
          name: "tts_api_key"
          description: {
            zh: "可选，TTS API Key"
            en: "Optional TTS API key"
          }
          type: string
          required: false
        },
        {
          name: "tts_headers"
          description: {
            zh: "可选，HTTP 类 TTS headers 的 JSON 对象字符串"
            en: "Optional JSON object string for HTTP-style TTS headers"
          }
          type: string
          required: false
        },
        {
          name: "tts_http_method"
          description: {
            zh: "可选，GET/POST"
            en: "Optional, GET/POST"
          }
          type: string
          required: false
        },
        {
          name: "tts_request_body"
          description: {
            zh: "可选，HTTP 类 TTS 的 POST body 模板。仅支持 `{text}`、`{rate}`、`{pitch}`、`{voice}`"
            en: "Optional POST body template for HTTP-style TTS providers. Supports only `{text}`, `{rate}`, `{pitch}`, `{voice}`"
          }
          type: string
          required: false
        },
        {
          name: "tts_content_type"
          description: {
            zh: "可选，TTS Content-Type"
            en: "Optional TTS content type"
          }
          type: string
          required: false
        },
        {
          name: "tts_locale"
          description: {
            zh: "可选，TTS 语言标签，例如 zh-CN 或 en-US"
            en: "Optional TTS locale tag, for example zh-CN or en-US"
          }
          type: string
          required: false
        },
        {
          name: "tts_voice_id"
          description: {
            zh: "可选，TTS 音色 ID。MIMO voiceclone 可填写完整 data:audio/...;base64,... 音频样本"
            en: "Optional TTS voice id. For MIMO voiceclone, this may be the full data:audio/...;base64,... audio sample"
          }
          type: string
          required: false
        },
        {
          name: "tts_model_name"
          description: {
            zh: "可选，TTS 模型名"
            en: "Optional TTS model name"
          }
          type: string
          required: false
        },
        {
          name: "tts_vits_package_path"
          description: {
            zh: "可选，本地 VITS/Piper TTS 模型包路径，支持 .zip 文件或已解压目录"
            en: "Optional local VITS/Piper TTS package path, supporting a .zip file or extracted package directory"
          }
          type: string
          required: false
        },
        {
          name: "tts_vits_speaker_id"
          description: {
            zh: "可选，VITS/Piper TTS 模型包需要的数字 speaker id"
            en: "Optional numeric speaker id required by the VITS/Piper TTS package"
          }
          type: string
          required: false
        },
        {
          name: "tts_vits_options"
          description: {
            zh: "可选，VITS/Piper TTS 模型包参数 JSON 对象字符串"
            en: "Optional JSON object string for VITS/Piper TTS package options"
          }
          type: string
          required: false
        },
        {
          name: "tts_response_pipeline"
          description: {
            zh: "可选，HTTP TTS 响应处理管线 JSON 数组字符串。留空或 `[]` 时保持旧行为，直接把响应体当音频"
            en: "Optional HTTP TTS response pipeline JSON array string. Leave empty or use `[]` to keep the old direct-audio behavior"
          }
          type: string
          required: false
        },
        {
          name: "tts_cleaner_regexs"
          description: {
            zh: "可选，TTS 清理正则列表 JSON 数组字符串"
            en: "Optional JSON array string for TTS cleaner regex list"
          }
          type: string
          required: false
        },
        {
          name: "tts_speech_rate"
          description: {
            zh: "可选，TTS 语速"
            en: "Optional TTS speech rate"
          }
          type: number
          required: false
        },
        {
          name: "tts_pitch"
          description: {
            zh: "可选，TTS 音调"
            en: "Optional TTS pitch"
          }
          type: number
          required: false
        },
        {
          name: "stt_service_type"
          description: {
            zh: "可选，SHERPA_NCNN/OPENAI_STT/DEEPGRAM_STT"
            en: "Optional, SHERPA_NCNN/OPENAI_STT/DEEPGRAM_STT"
          }
          type: string
          required: false
        },
        {
          name: "stt_endpoint_url"
          description: {
            zh: "可选，STT endpoint URL"
            en: "Optional STT endpoint URL"
          }
          type: string
          required: false
        },
        {
          name: "stt_api_key"
          description: {
            zh: "可选，STT API Key"
            en: "Optional STT API key"
          }
          type: string
          required: false
        },
        {
          name: "stt_model_name"
          description: {
            zh: "可选，STT 模型名"
            en: "Optional STT model name"
          }
          type: string
          required: false
        }
      ]
    },
    {
      name: "test_tts_playback"
      description: {
        zh: '''按当前 TTS 配置播放一次测试文本。'''
        en: '''Play one TTS test utterance with the current configuration.'''
      }
      parameters: [
        {
          name: "text"
          description: {
            zh: "必填，要播放的测试文本"
            en: "Required test text to play"
          }
          type: string
          required: true
        },
        {
          name: "interrupt"
          description: {
            zh: "可选，播放前是否先中断当前播报"
            en: "Optional, interrupt current playback before this test"
          }
          type: boolean
          required: false
        },
        {
          name: "speech_rate"
          description: {
            zh: "可选，仅本次测试生效的语速覆盖值"
            en: "Optional speech-rate override for this test only"
          }
          type: number
          required: false
        },
        {
          name: "pitch"
          description: {
            zh: "可选，仅本次测试生效的音调覆盖值"
            en: "Optional pitch override for this test only"
          }
          type: number
          required: false
        }
      ]
    },
    {
      name: "list_model_configs"
      description: {
        zh: '''列出全部模型配置及功能模型绑定关系。'''
        en: '''List all model configs and function-model bindings.'''
      }
      parameters: []
    },
    {
      name: "create_model_config"
      description: {
        zh: '''新增模型配置（可带初始化字段）。'''
        en: '''Create a model config (optional initialization fields).'''
      }
      parameters: [
        {
          name: "name"
          description: {
            zh: "可选，配置名称"
            en: "Optional config name"
          }
          type: string
          required: false
        },
        {
          name: "api_provider_type"
          description: {
            zh: "可选，提供商枚举名（如 OPENAI_GENERIC/OPENAI_LOCAL/OPENAI_RESPONSES_GENERIC/DEEPSEEK/GEMINI_GENERIC/LMSTUDIO/OLLAMA/MNN/LLAMA_CPP；其中 LMSTUDIO/OLLAMA/OPENAI_LOCAL/MNN/LLAMA_CPP 为本地模型链路）"
            en: "Optional provider enum name (e.g. OPENAI_GENERIC/OPENAI_LOCAL/OPENAI_RESPONSES_GENERIC/DEEPSEEK/GEMINI_GENERIC/LMSTUDIO/OLLAMA/MNN/LLAMA_CPP; LMSTUDIO/OLLAMA/OPENAI_LOCAL/MNN/LLAMA_CPP are local-model providers)"
          }
          type: string
          required: false
        },
        {
          name: "api_endpoint"
          description: {
            zh: "可选，API端点"
            en: "Optional API endpoint"
          }
          type: string
          required: false
        },
        {
          name: "api_key"
          description: {
            zh: "可选，API Key"
            en: "Optional API key"
          }
          type: string
          required: false
        },
        {
          name: "model_name"
          description: {
            zh: "可选，模型名（多个可逗号分隔）"
            en: "Optional model name (comma-separated for multiple models)"
          }
          type: string
          required: false
        },
        {
          name: "max_tokens_enabled"
          description: {
            zh: "可选，是否启用 max_tokens 参数"
            en: "Optional switch for max_tokens"
          }
          type: boolean
          required: false
        },
        {
          name: "max_tokens"
          description: {
            zh: "可选，max_tokens 数值"
            en: "Optional max_tokens value"
          }
          type: integer
          required: false
        },
        {
          name: "temperature_enabled"
          description: {
            zh: "可选，是否启用 temperature 参数"
            en: "Optional switch for temperature"
          }
          type: boolean
          required: false
        },
        {
          name: "temperature"
          description: {
            zh: "可选，temperature 数值"
            en: "Optional temperature value"
          }
          type: number
          required: false
        },
        {
          name: "top_p_enabled"
          description: {
            zh: "可选，是否启用 top_p 参数"
            en: "Optional switch for top_p"
          }
          type: boolean
          required: false
        },
        {
          name: "top_p"
          description: {
            zh: "可选，top_p 数值"
            en: "Optional top_p value"
          }
          type: number
          required: false
        },
        {
          name: "top_k_enabled"
          description: {
            zh: "可选，是否启用 top_k 参数"
            en: "Optional switch for top_k"
          }
          type: boolean
          required: false
        },
        {
          name: "top_k"
          description: {
            zh: "可选，top_k 数值"
            en: "Optional top_k value"
          }
          type: integer
          required: false
        },
        {
          name: "presence_penalty_enabled"
          description: {
            zh: "可选，是否启用 presence_penalty 参数"
            en: "Optional switch for presence_penalty"
          }
          type: boolean
          required: false
        },
        {
          name: "presence_penalty"
          description: {
            zh: "可选，presence_penalty 数值"
            en: "Optional presence_penalty value"
          }
          type: number
          required: false
        },
        {
          name: "frequency_penalty_enabled"
          description: {
            zh: "可选，是否启用 frequency_penalty 参数"
            en: "Optional switch for frequency_penalty"
          }
          type: boolean
          required: false
        },
        {
          name: "frequency_penalty"
          description: {
            zh: "可选，frequency_penalty 数值"
            en: "Optional frequency_penalty value"
          }
          type: number
          required: false
        },
        {
          name: "repetition_penalty_enabled"
          description: {
            zh: "可选，是否启用 repetition_penalty 参数"
            en: "Optional switch for repetition_penalty"
          }
          type: boolean
          required: false
        },
        {
          name: "repetition_penalty"
          description: {
            zh: "可选，repetition_penalty 数值"
            en: "Optional repetition_penalty value"
          }
          type: number
          required: false
        },
        {
          name: "custom_parameters"
          description: {
            zh: "可选，自定义参数 JSON 字符串"
            en: "Optional custom parameters JSON string"
          }
          type: string
          required: false
        },
        {
          name: "custom_headers"
          description: {
            zh: "可选，自定义请求头 JSON 对象字符串"
            en: "Optional custom request headers JSON object string"
          }
          type: string
          required: false
        },
        {
          name: "context_length"
          description: {
            zh: "可选，上下文长度倍率"
            en: "Optional context length multiplier"
          }
          type: number
          required: false
        },
        {
          name: "max_context_length"
          description: {
            zh: "可选，最大上下文长度倍率"
            en: "Optional max context length multiplier"
          }
          type: number
          required: false
        },
        {
          name: "enable_max_context_mode"
          description: {
            zh: "可选，是否启用最大上下文模式"
            en: "Optional max-context mode switch"
          }
          type: boolean
          required: false
        },
        {
          name: "summary_token_threshold"
          description: {
            zh: "可选，总结触发阈值"
            en: "Optional summary trigger threshold"
          }
          type: number
          required: false
        },
        {
          name: "enable_summary"
          description: {
            zh: "可选，是否启用总结"
            en: "Optional summary switch"
          }
          type: boolean
          required: false
        },
        {
          name: "enable_summary_by_message_count"
          description: {
            zh: "可选，是否按消息数触发总结"
            en: "Optional summary-by-message-count switch"
          }
          type: boolean
          required: false
        },
        {
          name: "summary_message_count_threshold"
          description: {
            zh: "可选，按消息数总结的阈值"
            en: "Optional message-count threshold for summary"
          }
          type: integer
          required: false
        },
        {
          name: "enable_direct_image_processing"
          description: {
            zh: "可选，是否启用直接图片处理"
            en: "Optional direct image processing switch"
          }
          type: boolean
          required: false
        },
        {
          name: "enable_direct_audio_processing"
          description: {
            zh: "可选，是否启用直接音频处理"
            en: "Optional direct audio processing switch"
          }
          type: boolean
          required: false
        },
        {
          name: "enable_direct_video_processing"
          description: {
            zh: "可选，是否启用直接视频处理"
            en: "Optional direct video processing switch"
          }
          type: boolean
          required: false
        },
        {
          name: "enable_google_search"
          description: {
            zh: "可选，是否启用 Google Search"
            en: "Optional Google Search switch"
          }
          type: boolean
          required: false
        },
        {
          name: "enable_claude_1h_prompt_cache"
          description: {
            zh: "可选，是否启用 Claude 1h Prompt Cache"
            en: "Optional Claude 1h prompt cache switch"
          }
          type: boolean
          required: false
        },
        {
          name: "enable_tool_call"
          description: {
            zh: "可选，是否开启Tool Call"
            en: "Optional tool-call switch"
          }
          type: boolean
          required: false
        },
        {
          name: "mnn_forward_type"
          description: {
            zh: "可选，MNN 前向类型"
            en: "Optional MNN forward type"
          }
          type: integer
          required: false
        },
        {
          name: "mnn_thread_count"
          description: {
            zh: "可选，MNN 线程数"
            en: "Optional MNN thread count"
          }
          type: integer
          required: false
        },
        {
          name: "llama_thread_count"
          description: {
            zh: "可选，llama.cpp 线程数"
            en: "Optional llama.cpp thread count"
          }
          type: integer
          required: false
        },
        {
          name: "llama_context_size"
          description: {
            zh: "可选，llama.cpp 上下文长度"
            en: "Optional llama.cpp context size"
          }
          type: integer
          required: false
        },
        {
          name: "llama_gpu_layers"
          description: {
            zh: "可选，llama.cpp GPU 层数"
            en: "Optional llama.cpp GPU layer count"
          }
          type: integer
          required: false
        },
        {
          name: "request_limit_per_minute"
          description: {
            zh: "可选，每分钟请求限制"
            en: "Optional request-per-minute limit"
          }
          type: integer
          required: false
        },
        {
          name: "max_concurrent_requests"
          description: {
            zh: "可选，最大并发请求数"
            en: "Optional max concurrent requests"
          }
          type: integer
          required: false
        }
      ]
    },
    {
      name: "update_model_config"
      description: {
        zh: '''按 config_id 修改模型配置。'''
        en: '''Update model config by config_id.'''
      }
      parameters: [
        {
          name: "config_id"
          description: {
            zh: "目标配置ID"
            en: "Target config id"
          }
          type: string
          required: true
        },
        {
          name: "name"
          description: {
            zh: "可选，配置名称"
            en: "Optional config name"
          }
          type: string
          required: false
        },
        {
          name: "api_provider_type"
          description: {
            zh: "可选，提供商枚举名（如 OPENAI_GENERIC/OPENAI_LOCAL/OPENAI_RESPONSES_GENERIC/DEEPSEEK/GEMINI_GENERIC/LMSTUDIO/OLLAMA/MNN/LLAMA_CPP；其中 LMSTUDIO/OLLAMA/OPENAI_LOCAL/MNN/LLAMA_CPP 为本地模型链路）"
            en: "Optional provider enum name (e.g. OPENAI_GENERIC/OPENAI_LOCAL/OPENAI_RESPONSES_GENERIC/DEEPSEEK/GEMINI_GENERIC/LMSTUDIO/OLLAMA/MNN/LLAMA_CPP; LMSTUDIO/OLLAMA/OPENAI_LOCAL/MNN/LLAMA_CPP are local-model providers)"
          }
          type: string
          required: false
        },
        {
          name: "api_endpoint"
          description: {
            zh: "可选，API端点"
            en: "Optional API endpoint"
          }
          type: string
          required: false
        },
        {
          name: "api_key"
          description: {
            zh: "可选，API Key"
            en: "Optional API key"
          }
          type: string
          required: false
        },
        {
          name: "model_name"
          description: {
            zh: "可选，模型名（多个可逗号分隔）"
            en: "Optional model name (comma-separated for multiple models)"
          }
          type: string
          required: false
        },
        {
          name: "max_tokens_enabled"
          description: {
            zh: "可选，是否启用 max_tokens 参数"
            en: "Optional switch for max_tokens"
          }
          type: boolean
          required: false
        },
        {
          name: "max_tokens"
          description: {
            zh: "可选，max_tokens 数值"
            en: "Optional max_tokens value"
          }
          type: integer
          required: false
        },
        {
          name: "temperature_enabled"
          description: {
            zh: "可选，是否启用 temperature 参数"
            en: "Optional switch for temperature"
          }
          type: boolean
          required: false
        },
        {
          name: "temperature"
          description: {
            zh: "可选，temperature 数值"
            en: "Optional temperature value"
          }
          type: number
          required: false
        },
        {
          name: "top_p_enabled"
          description: {
            zh: "可选，是否启用 top_p 参数"
            en: "Optional switch for top_p"
          }
          type: boolean
          required: false
        },
        {
          name: "top_p"
          description: {
            zh: "可选，top_p 数值"
            en: "Optional top_p value"
          }
          type: number
          required: false
        },
        {
          name: "top_k_enabled"
          description: {
            zh: "可选，是否启用 top_k 参数"
            en: "Optional switch for top_k"
          }
          type: boolean
          required: false
        },
        {
          name: "top_k"
          description: {
            zh: "可选，top_k 数值"
            en: "Optional top_k value"
          }
          type: integer
          required: false
        },
        {
          name: "presence_penalty_enabled"
          description: {
            zh: "可选，是否启用 presence_penalty 参数"
            en: "Optional switch for presence_penalty"
          }
          type: boolean
          required: false
        },
        {
          name: "presence_penalty"
          description: {
            zh: "可选，presence_penalty 数值"
            en: "Optional presence_penalty value"
          }
          type: number
          required: false
        },
        {
          name: "frequency_penalty_enabled"
          description: {
            zh: "可选，是否启用 frequency_penalty 参数"
            en: "Optional switch for frequency_penalty"
          }
          type: boolean
          required: false
        },
        {
          name: "frequency_penalty"
          description: {
            zh: "可选，frequency_penalty 数值"
            en: "Optional frequency_penalty value"
          }
          type: number
          required: false
        },
        {
          name: "repetition_penalty_enabled"
          description: {
            zh: "可选，是否启用 repetition_penalty 参数"
            en: "Optional switch for repetition_penalty"
          }
          type: boolean
          required: false
        },
        {
          name: "repetition_penalty"
          description: {
            zh: "可选，repetition_penalty 数值"
            en: "Optional repetition_penalty value"
          }
          type: number
          required: false
        },
        {
          name: "custom_parameters"
          description: {
            zh: "可选，自定义参数 JSON 字符串"
            en: "Optional custom parameters JSON string"
          }
          type: string
          required: false
        },
        {
          name: "custom_headers"
          description: {
            zh: "可选，自定义请求头 JSON 对象字符串"
            en: "Optional custom request headers JSON object string"
          }
          type: string
          required: false
        },
        {
          name: "context_length"
          description: {
            zh: "可选，上下文长度倍率"
            en: "Optional context length multiplier"
          }
          type: number
          required: false
        },
        {
          name: "max_context_length"
          description: {
            zh: "可选，最大上下文长度倍率"
            en: "Optional max context length multiplier"
          }
          type: number
          required: false
        },
        {
          name: "enable_max_context_mode"
          description: {
            zh: "可选，是否启用最大上下文模式"
            en: "Optional max-context mode switch"
          }
          type: boolean
          required: false
        },
        {
          name: "summary_token_threshold"
          description: {
            zh: "可选，总结触发阈值"
            en: "Optional summary trigger threshold"
          }
          type: number
          required: false
        },
        {
          name: "enable_summary"
          description: {
            zh: "可选，是否启用总结"
            en: "Optional summary switch"
          }
          type: boolean
          required: false
        },
        {
          name: "enable_summary_by_message_count"
          description: {
            zh: "可选，是否按消息数触发总结"
            en: "Optional summary-by-message-count switch"
          }
          type: boolean
          required: false
        },
        {
          name: "summary_message_count_threshold"
          description: {
            zh: "可选，按消息数总结的阈值"
            en: "Optional message-count threshold for summary"
          }
          type: integer
          required: false
        },
        {
          name: "enable_direct_image_processing"
          description: {
            zh: "可选，是否启用直接图片处理"
            en: "Optional direct image processing switch"
          }
          type: boolean
          required: false
        },
        {
          name: "enable_direct_audio_processing"
          description: {
            zh: "可选，是否启用直接音频处理"
            en: "Optional direct audio processing switch"
          }
          type: boolean
          required: false
        },
        {
          name: "enable_direct_video_processing"
          description: {
            zh: "可选，是否启用直接视频处理"
            en: "Optional direct video processing switch"
          }
          type: boolean
          required: false
        },
        {
          name: "enable_google_search"
          description: {
            zh: "可选，是否启用 Google Search"
            en: "Optional Google Search switch"
          }
          type: boolean
          required: false
        },
        {
          name: "enable_claude_1h_prompt_cache"
          description: {
            zh: "可选，是否启用 Claude 1h Prompt Cache"
            en: "Optional Claude 1h prompt cache switch"
          }
          type: boolean
          required: false
        },
        {
          name: "enable_tool_call"
          description: {
            zh: "可选，是否开启Tool Call"
            en: "Optional tool-call switch"
          }
          type: boolean
          required: false
        },
        {
          name: "mnn_forward_type"
          description: {
            zh: "可选，MNN 前向类型"
            en: "Optional MNN forward type"
          }
          type: integer
          required: false
        },
        {
          name: "mnn_thread_count"
          description: {
            zh: "可选，MNN 线程数"
            en: "Optional MNN thread count"
          }
          type: integer
          required: false
        },
        {
          name: "llama_thread_count"
          description: {
            zh: "可选，llama.cpp 线程数"
            en: "Optional llama.cpp thread count"
          }
          type: integer
          required: false
        },
        {
          name: "llama_context_size"
          description: {
            zh: "可选，llama.cpp 上下文长度"
            en: "Optional llama.cpp context size"
          }
          type: integer
          required: false
        },
        {
          name: "llama_gpu_layers"
          description: {
            zh: "可选，llama.cpp GPU 层数"
            en: "Optional llama.cpp GPU layer count"
          }
          type: integer
          required: false
        },
        {
          name: "request_limit_per_minute"
          description: {
            zh: "可选，每分钟请求限制"
            en: "Optional request-per-minute limit"
          }
          type: integer
          required: false
        },
        {
          name: "max_concurrent_requests"
          description: {
            zh: "可选，最大并发请求数"
            en: "Optional max concurrent requests"
          }
          type: integer
          required: false
        }
      ]
    },
    {
      name: "delete_model_config"
      description: {
        zh: '''按 config_id 删除模型配置（默认配置不可删）。'''
        en: '''Delete model config by config_id (default cannot be deleted).'''
      }
      parameters: [
        {
          name: "config_id"
          description: {
            zh: "目标配置ID"
            en: "Target config id"
          }
          type: string
          required: true
        }
      ]
    },
    {
      name: "list_function_model_configs"
      description: {
        zh: '''仅列出功能模型绑定关系（功能 -> 配置 + 模型索引）。'''
        en: '''List function model bindings only (function -> config + model index).'''
      }
      parameters: []
    },
    {
      name: "get_function_model_config"
      description: {
        zh: '''查看某个功能当前绑定的单个模型配置详情。'''
        en: '''Get one function's currently bound model config detail.'''
      }
      parameters: [
        {
          name: "function_type"
          description: {
            zh: "功能类型枚举名"
            en: "Function type enum name"
          }
          type: string
          required: true
        }
      ]
    },
    {
      name: "get_context_summary_config"
      description: {
        zh: '''获取某个功能当前绑定模型配置中的上下文总结参数。'''
        en: '''Get context-summary settings from the model config bound to a function.'''
      }
      parameters: [
        {
          name: "function_type"
          description: {
            zh: "可选，功能类型；默认 CHAT"
            en: "Optional function type; default CHAT"
          }
          type: string
          required: false
        }
      ]
    },
    {
      name: "set_context_summary_config"
      description: {
        zh: '''为某个功能绑定配置设置上下文总结参数（可选覆盖默认值）。'''
        en: '''Set context-summary settings for a function binding (optional overrides supported).'''
      }
      parameters: [
        {
          name: "function_type"
          description: {
            zh: "可选，功能类型；默认 CHAT"
            en: "Optional function type; default CHAT"
          }
          type: string
          required: false
        },
        {
          name: "context_length"
          description: {
            zh: "可选，基础上下文长度"
            en: "Optional base context length"
          }
          type: number
          required: false
        },
        {
          name: "max_context_length"
          description: {
            zh: "可选，最大上下文长度"
            en: "Optional max context length"
          }
          type: number
          required: false
        },
        {
          name: "enable_max_context_mode"
          description: {
            zh: "可选，是否启用最大上下文模式"
            en: "Optional max-context-mode switch"
          }
          type: boolean
          required: false
        },
        {
          name: "summary_token_threshold"
          description: {
            zh: "可选，总结触发 token 阈值（0~1）"
            en: "Optional token-ratio threshold for summary trigger (0~1)"
          }
          type: number
          required: false
        },
        {
          name: "enable_summary"
          description: {
            zh: "可选，是否启用上下文总结"
            en: "Optional context-summary switch"
          }
          type: boolean
          required: false
        },
        {
          name: "enable_summary_by_message_count"
          description: {
            zh: "可选，是否启用按消息条数触发总结"
            en: "Optional message-count summary trigger switch"
          }
          type: boolean
          required: false
        },
        {
          name: "summary_message_count_threshold"
          description: {
            zh: "可选，按消息条数触发总结阈值"
            en: "Optional message-count threshold for summary trigger"
          }
          type: integer
          required: false
        }
      ]
    },
    {
      name: "set_function_model_config"
      description: {
        zh: '''为功能指定模型配置与模型索引。'''
        en: '''Set model config and model index for a function.'''
      }
      parameters: [
        {
          name: "function_type"
          description: {
            zh: "功能类型枚举名"
            en: "Function type enum name"
          }
          type: string
          required: true
        },
        {
          name: "config_id"
          description: {
            zh: "模型配置ID"
            en: "Model config id"
          }
          type: string
          required: true
        },
        {
          name: "model_index"
          description: {
            zh: "可选，模型索引"
            en: "Optional model index"
          }
          type: integer
          required: false
        }
      ]
    },
    {
      name: "test_model_config_connection"
      description: {
        zh: '''按设置页同等逻辑测试某个模型配置。'''
        en: '''Run settings-UI-equivalent tests for one model config.'''
      }
      parameters: [
        {
          name: "config_id"
          description: {
            zh: "目标配置ID"
            en: "Target config id"
          }
          type: string
          required: true
        },
        {
          name: "model_index"
          description: {
            zh: "可选，模型索引"
            en: "Optional model index"
          }
          type: integer
          required: false
        }
      ]
    },
    {
      name: "list_character_cards"
      description: {
        zh: '''列出完整角色卡配置及当前活跃角色卡。'''
        en: '''List full character-card settings and the active character card.'''
      }
      parameters: []
    },
    {
      name: "get_character_card"
      description: {
        zh: '''按角色卡 ID 获取完整配置。'''
        en: '''Get one full character-card configuration by id.'''
      }
      parameters: [
        {
          name: "character_card_id"
          description: { zh: "角色卡 ID" en: "Character card id" }
          type: string
          required: true
        }
      ]
    },
    {
      name: "create_character_card"
      description: {
        zh: '''创建角色卡。name 必填；列表字段传 JSON 字符串数组。'''
        en: '''Create a character card. name is required; list fields use JSON string arrays.'''
      }
      parameters: [
        {
          name: "name"
          description: { zh: "角色卡名称" en: "Character card name" }
          type: string
          required: true
        },
        {
          name: "description"
          description: { zh: "可选，简介" en: "Optional description" }
          type: string
          required: false
        },
        {
          name: "character_setting"
          description: { zh: "可选，角色设定提示词" en: "Optional character-setting prompt" }
          type: string
          required: false
        },
        {
          name: "opening_statement"
          description: { zh: "可选，开场白" en: "Optional opening statement" }
          type: string
          required: false
        },
        {
          name: "other_content_chat"
          description: { zh: "可选，聊天附加内容" en: "Optional chat content" }
          type: string
          required: false
        },
        {
          name: "other_content_voice"
          description: { zh: "可选，语音附加内容" en: "Optional voice content" }
          type: string
          required: false
        },
        {
          name: "attached_tag_ids"
          description: { zh: "可选，标签 ID 的 JSON 字符串数组" en: "Optional JSON string array of tag ids" }
          type: string
          required: false
        },
        {
          name: "advanced_custom_prompt"
          description: { zh: "可选，高级自定义提示词" en: "Optional advanced custom prompt" }
          type: string
          required: false
        },
        {
          name: "marks"
          description: { zh: "可选，备注" en: "Optional marks" }
          type: string
          required: false
        },
        {
          name: "chat_model_binding_mode"
          description: { zh: "可选，FOLLOW_GLOBAL 或 FIXED_CONFIG" en: "Optional FOLLOW_GLOBAL or FIXED_CONFIG" }
          type: string
          required: false
        },
        {
          name: "chat_model_config_id"
          description: { zh: "可选，固定对话模型配置 ID；空字符串清除" en: "Optional fixed chat-model config id; empty string clears" }
          type: string
          required: false
        },
        {
          name: "chat_model_index"
          description: { zh: "可选，固定对话模型索引" en: "Optional fixed chat-model index" }
          type: integer
          required: false
        },
        {
          name: "memory_profile_binding_mode"
          description: { zh: "可选，FOLLOW_GLOBAL 或 FIXED_PROFILE" en: "Optional FOLLOW_GLOBAL or FIXED_PROFILE" }
          type: string
          required: false
        },
        {
          name: "memory_profile_id"
          description: { zh: "可选，固定记忆配置 ID；空字符串清除" en: "Optional fixed memory-profile id; empty string clears" }
          type: string
          required: false
        },
        {
          name: "tool_access_enabled"
          description: { zh: "可选，启用角色卡工具白名单" en: "Optional switch for the card tool allowlist" }
          type: boolean
          required: false
        },
        {
          name: "allowed_builtin_tools"
          description: { zh: "可选，内置工具名的 JSON 字符串数组" en: "Optional JSON string array of built-in tool names" }
          type: string
          required: false
        },
        {
          name: "allowed_packages"
          description: { zh: "可选，包名的 JSON 字符串数组" en: "Optional JSON string array of package names" }
          type: string
          required: false
        },
        {
          name: "allowed_skills"
          description: { zh: "可选，Skill 名称的 JSON 字符串数组" en: "Optional JSON string array of skill names" }
          type: string
          required: false
        },
        {
          name: "allowed_mcp_servers"
          description: { zh: "可选，MCP 服务名的 JSON 字符串数组" en: "Optional JSON string array of MCP server names" }
          type: string
          required: false
        }
      ]
    },
    {
      name: "update_character_card"
      description: {
        zh: '''按角色卡 ID 更新提供的字段。除 ID 外的字段定义与 create_character_card 一致。'''
        en: '''Update supplied fields by character-card id. The editable fields match create_character_card.'''
      }
      parameters: [
        {
          name: "character_card_id"
          description: { zh: "角色卡 ID" en: "Character card id" }
          type: string
          required: true
        },
        {
          name: "name"
          description: { zh: "可选，角色卡名称" en: "Optional character card name" }
          type: string
          required: false
        },
        {
          name: "description"
          description: { zh: "可选，简介" en: "Optional description" }
          type: string
          required: false
        },
        {
          name: "character_setting"
          description: { zh: "可选，角色设定提示词" en: "Optional character-setting prompt" }
          type: string
          required: false
        },
        {
          name: "opening_statement"
          description: { zh: "可选，开场白" en: "Optional opening statement" }
          type: string
          required: false
        },
        {
          name: "other_content_chat"
          description: { zh: "可选，聊天附加内容" en: "Optional chat content" }
          type: string
          required: false
        },
        {
          name: "other_content_voice"
          description: { zh: "可选，语音附加内容" en: "Optional voice content" }
          type: string
          required: false
        },
        {
          name: "attached_tag_ids"
          description: { zh: "可选，标签 ID 的 JSON 字符串数组" en: "Optional JSON string array of tag ids" }
          type: string
          required: false
        },
        {
          name: "advanced_custom_prompt"
          description: { zh: "可选，高级自定义提示词" en: "Optional advanced custom prompt" }
          type: string
          required: false
        },
        {
          name: "marks"
          description: { zh: "可选，备注" en: "Optional marks" }
          type: string
          required: false
        },
        {
          name: "chat_model_binding_mode"
          description: { zh: "可选，FOLLOW_GLOBAL 或 FIXED_CONFIG" en: "Optional FOLLOW_GLOBAL or FIXED_CONFIG" }
          type: string
          required: false
        },
        {
          name: "chat_model_config_id"
          description: { zh: "可选，固定对话模型配置 ID；空字符串清除" en: "Optional fixed chat-model config id; empty string clears" }
          type: string
          required: false
        },
        {
          name: "chat_model_index"
          description: { zh: "可选，固定对话模型索引" en: "Optional fixed chat-model index" }
          type: integer
          required: false
        },
        {
          name: "memory_profile_binding_mode"
          description: { zh: "可选，FOLLOW_GLOBAL 或 FIXED_PROFILE" en: "Optional FOLLOW_GLOBAL or FIXED_PROFILE" }
          type: string
          required: false
        },
        {
          name: "memory_profile_id"
          description: { zh: "可选，固定记忆配置 ID；空字符串清除" en: "Optional fixed memory-profile id; empty string clears" }
          type: string
          required: false
        },
        {
          name: "tool_access_enabled"
          description: { zh: "可选，启用角色卡工具白名单" en: "Optional switch for the card tool allowlist" }
          type: boolean
          required: false
        },
        {
          name: "allowed_builtin_tools"
          description: { zh: "可选，内置工具名的 JSON 字符串数组" en: "Optional JSON string array of built-in tool names" }
          type: string
          required: false
        },
        {
          name: "allowed_packages"
          description: { zh: "可选，包名的 JSON 字符串数组" en: "Optional JSON string array of package names" }
          type: string
          required: false
        },
        {
          name: "allowed_skills"
          description: { zh: "可选，Skill 名称的 JSON 字符串数组" en: "Optional JSON string array of skill names" }
          type: string
          required: false
        },
        {
          name: "allowed_mcp_servers"
          description: { zh: "可选，MCP 服务名的 JSON 字符串数组" en: "Optional JSON string array of MCP server names" }
          type: string
          required: false
        }
      ]
    },
    {
      name: "delete_character_card"
      description: {
        zh: '''删除非默认角色卡。'''
        en: '''Delete a non-default character card.'''
      }
      parameters: [
        {
          name: "character_card_id"
          description: { zh: "角色卡 ID" en: "Character card id" }
          type: string
          required: true
        }
      ]
    },
    {
      name: "set_active_character_card"
      description: {
        zh: '''将指定角色卡设为活跃角色卡。'''
        en: '''Set an existing character card as active.'''
      }
      parameters: [
        {
          name: "character_card_id"
          description: { zh: "角色卡 ID" en: "Character card id" }
          type: string
          required: true
        }
      ]
    },
    {
      name: "clear_active_character_card"
      description: {
        zh: '''清除当前活跃角色卡。'''
        en: '''Clear the current active character card.'''
      }
      parameters: []
    },
    {
      name: "import_character_card_from_tavern_json"
      description: {
        zh: '''从 Tavern JSON 导入一张角色卡。'''
        en: '''Import one character card from Tavern JSON.'''
      }
      parameters: [
        {
          name: "tavern_json"
          description: { zh: "Tavern 角色卡 JSON 内容" en: "Tavern character-card JSON content" }
          type: string
          required: true
        }
      ]
    },
    {
      name: "export_character_card_to_tavern_json"
      description: {
        zh: '''将一张角色卡导出为 Tavern JSON。'''
        en: '''Export one character card as Tavern JSON.'''
      }
      parameters: [
        {
          name: "character_card_id"
          description: { zh: "角色卡 ID" en: "Character card id" }
          type: string
          required: true
        }
      ]
    },
    {
      name: "ping_mcp"
      description: {
        zh: '''直通 use_package 的探测工具：用于快速测试某个 package 是否可被加载（MCP/Skill/Sandbox 三兼容）。'''
        en: '''A pass-through probe for use_package: quickly test whether a package can be loaded (tri-compatible across MCP/Skill/Sandbox).'''
      }
      parameters: [
        {
          name: "package_name"
          description: {
            zh: "要探测的包名"
            en: "Package name to probe"
          }
          type: string
          required: true
        }
      ]
    }
  ]
}*/
"""

        val TIME = """
/* METADATA
{
  name: time

  display_name: {
    zh: "时间"
    en: "Time"
  }
  description: {
    zh: "提供时间相关功能。实际上，激活本包的同时已经能够获取时间了。"
    en: "Provides time-related utilities. In practice, current time is already available once this package is enabled."
  }
  enabledByDefault: true
  category: "Utility"
  tools: [
    {
      name: get_time
      description: {
        zh: "获取当前时间。当使用此包时，AI已经自动获取了当前的时间信息。"
        en: "Get the current time. When using this package, the AI may already have the current time context."
      }
      parameters: []
    },
    {
      name: format_time
      description: {
        zh: "格式化时间。提供各种时间格式化选项。"
        en: "Format time. Provides various time formatting options."
      }
      parameters: []
    }
  ]
}*/
"""

        val VARIOUS_SEARCH = """
/* METADATA
{
  name: various_search

  display_name: {
    zh: "多平台搜索"
    en: "Multi-Platform Search"
  }
  category: "Search"
  description: { zh: "提供多平台搜索功能（含图片搜索），支持从必应、百度、搜狗、夸克等平台获取搜索结果。", en: "Multi-platform search tools (including image search) that fetch results from Bing, Baidu, Sogou, Quark, and more." }
  enabledByDefault: true
  
  tools: [
    {
      name: search_bing
      description: { zh: "使用必应搜索引擎进行搜索", en: "Search using the Bing search engine." }
      parameters: [
        {
          name: query
          description: { zh: "搜索查询关键词", en: "Search query keywords." }
          type: string
          required: true
        },
        {
          name: includeLinks
          description: { zh: "是否在结果中包含可点击的链接列表，默认为false。如果为true，AI可以根据返回的链接序号进行深入访问。", en: "Whether to include a clickable link list in results (default: false). If true, the AI can follow links by index." }
          type: boolean
          required: false
        }
      ]
    },
    {
      name: search_baidu
      description: { zh: "使用百度搜索引擎进行搜索", en: "Search using the Baidu search engine." }
      parameters: [
        {
          name: query
          description: { zh: "搜索查询关键词", en: "Search query keywords." }
          type: string
          required: true
        },
        {
          name: page
          description: { zh: "搜索结果页码，默认为1", en: "Result page number (default: 1)." }
          type: string
          required: false
        },
        {
          name: includeLinks
          description: { zh: "是否在结果中包含可点击的链接列表，默认为false。如果为true，AI可以根据返回的链接序号进行深入访问。", en: "Whether to include a clickable link list in results (default: false). If true, the AI can follow links by index." }
          type: boolean
          required: false
        }
      ]
    },
    {
      name: search_sogou
      description: { zh: "使用搜狗搜索引擎进行搜索", en: "Search using the Sogou search engine." }
      parameters: [
        {
          name: query
          description: { zh: "搜索查询关键词", en: "Search query keywords." }
          type: string
          required: true
        },
        {
          name: page
          description: { zh: "搜索结果页码，默认为1", en: "Result page number (default: 1)." }
          type: string
          required: false
        },
        {
          name: includeLinks
          description: { zh: "是否在结果中包含可点击的链接列表，默认为false。如果为true，AI可以根据返回的链接序号进行深入访问。", en: "Whether to include a clickable link list in results (default: false). If true, the AI can follow links by index." }
          type: boolean
          required: false
        }
      ]
    },
    {
      name: search_quark
      description: { zh: "使用夸克搜索引擎进行搜索", en: "Search using the Quark search engine." }
      parameters: [
        {
          name: query
          description: { zh: "搜索查询关键词", en: "Search query keywords." }
          type: string
          required: true
        },
        {
          name: page
          description: { zh: "搜索结果页码，默认为1", en: "Result page number (default: 1)." }
          type: string
          required: false
        },
        {
          name: includeLinks
          description: { zh: "是否在结果中包含可点击的链接列表，默认为false。如果为true，AI可以根据返回的链接序号进行深入访问。", en: "Whether to include a clickable link list in results (default: false). If true, the AI can follow links by index." }
          type: boolean
          required: false
        }
      ]
    },
    {
      name: combined_search
      description: { zh: "在多个平台同时执行搜索。建议用户要求搜索的时候默认使用这个工具。", en: "Run searches across multiple platforms. Use this tool by default when the user asks to search." }
      parameters: [
        {
          name: query
          description: { zh: "搜索查询关键词", en: "Search query keywords." }
          type: string
          required: true
        },
        {
          name: platforms
          description: { zh: "搜索平台列表字符串，可选值包括\"bing\",\"baidu\",\"sogou\",\"quark\"，多个平台用逗号分隔，比如\"bing,baidu,sogou,quark\"", en: "Comma-separated platform list. Supported: \"bing\", \"baidu\", \"sogou\", \"quark\". Example: \"bing,baidu,sogou,quark\"." }
          type: string
          required: true
        },
        {
          name: includeLinks
          description: { zh: "是否在结果中包含可点击的链接列表，默认为false。聚合搜索时建议保持为false以节省输出，仅在需要深入访问时对单个搜索引擎使用。", en: "Whether to include a clickable link list in results (default: false). For combined search, keep it false to reduce output; enable it for a single engine when you need to open links." }
          type: boolean
          required: false
        }
      ]
    },
    {
      name: search
      description: { zh: "兼容工具名：等同于 combined_search。用于处理模型误调用 search 的情况。", en: "Compatibility alias: equivalent to combined_search. Helps when models call search by mistake." }
      parameters: [
        {
          name: query
          description: { zh: "搜索查询关键词", en: "Search query keywords." }
          type: string
          required: true
        },
        {
          name: platforms
          description: { zh: "可选平台列表，默认 bing,baidu,sogou,quark", en: "Optional platform list, default bing,baidu,sogou,quark." }
          type: string
          required: false
        },
        {
          name: includeLinks
          description: { zh: "是否返回链接列表，默认 false", en: "Whether to include links in result, default false." }
          type: boolean
          required: false
        }
      ]
    },
    {
      name: search_web
      description: { zh: "兼容工具名：网页搜索别名。默认复用 combined_search 的统一搜索逻辑。", en: "Compatibility alias for web search. Reuses the unified combined_search flow." }
      parameters: [
        {
          name: query
          description: { zh: "搜索查询关键词", en: "Search query keywords." }
          type: string
          required: true
        },
        {
          name: platforms
          description: { zh: "可选平台列表，默认 bing,baidu,sogou,quark", en: "Optional platform list, default bing,baidu,sogou,quark." }
          type: string
          required: false
        },
        {
          name: includeLinks
          description: { zh: "是否返回链接列表，默认 false", en: "Whether to include links in result, default false." }
          type: boolean
          required: false
        }
      ]
    },
    {
      name: search_bing_images
      description: { zh: "使用必应图片搜索引擎进行图片搜索。返回内容会包含 visitKey 和 Images 编号；下载图片请用 download_file 的 visit_key + image_number（不要用 link_number 乱点页面链接）。", en: "Search images using Bing Images. The result includes visitKey and indexed Images; download images via download_file with visit_key + image_number (do not follow random page links via link_number)." }
      parameters: [
        {
          name: query
          description: { zh: "搜索关键词", en: "Search query keywords." }
          type: string
          required: true
        }
      ]
    },
    {
      name: search_wikimedia_images
      description: { zh: "使用 Wikimedia Commons 进行图片搜索（公共资源）。返回 visitKey + Images 编号；下载图片用 download_file(visit_key + image_number)。", en: "Search images using Wikimedia Commons (public domain/commons). Use visitKey + image_number with download_file to download images." }
      parameters: [
        {
          name: query
          description: { zh: "搜索关键词", en: "Search query keywords." }
          type: string
          required: true
        }
      ]
    },
    {
      name: search_duckduckgo_images
      description: { zh: "使用 DuckDuckGo Images 进行图片搜索。返回 visitKey + Images 编号；下载图片用 download_file(visit_key + image_number)。", en: "Search images using DuckDuckGo Images. Use visitKey + image_number with download_file to download images." }
      parameters: [
        {
          name: query
          description: { zh: "搜索关键词", en: "Search query keywords." }
          type: string
          required: true
        }
      ]
    },
    {
      name: search_ecosia_images
      description: { zh: "使用 Ecosia Images 进行图片搜索。返回 visitKey + Images 编号；下载图片用 download_file(visit_key + image_number)。", en: "Search images using Ecosia Images. Use visitKey + image_number with download_file to download images." }
      parameters: [
        {
          name: query
          description: { zh: "搜索关键词", en: "Search query keywords." }
          type: string
          required: true
        }
      ]
    },
    {
      name: search_pexels_images
      description: { zh: "使用 Pexels 进行图片搜索（高质量图库）。返回 visitKey + Images 编号；下载图片请用 download_file 的 visit_key + image_number。", en: "Search images using Pexels (high-quality stock). Use visitKey + image_number with download_file to download images." }
      parameters: [
        {
          name: query
          description: { zh: "搜索关键词", en: "Search query keywords." }
          type: string
          required: true
        }
      ]
    },
    {
      name: search_pixabay_images
      description: { zh: "使用 Pixabay 进行图片搜索（图库）。返回 visitKey + Images 编号；下载图片请用 download_file 的 visit_key + image_number。", en: "Search images using Pixabay (stock). Use visitKey + image_number with download_file to download images." }
      parameters: [
        {
          name: query
          description: { zh: "搜索关键词", en: "Search query keywords." }
          type: string
          required: true
        }
      ]
    }
  ]
}*/
"""

        val WORKFLOW = """
/* METADATA
{
  name: "workflow"

  display_name: {
    zh: "工作流管理"
    en: "Workflow Management"
  }
  description: {
    zh: '''工作流管理工具：创建/查询/更新/启用/禁用/删除/触发执行；支持 on_success/on_error 分支；支持语音触发（speech）。'''
    en: '''Workflow management tools for creating/querying/updating/enabling/disabling/deleting workflows, triggering execution, and branching via on_success/on_error. Supports speech trigger (speech).'''
  }
  "category": "Workflow",
  enabledByDefault: true

  tools: [
    {
      name: "usage_advice"
      description: {
        zh: '''
工作流工具使用建议（给 AI）：

- 核心概念（请优先对齐这些语义）：
  - 节点类型：trigger/execute/condition/logic/extract
  - 触发节点类型：manual/schedule/tasker/intent/speech
  - 参数引用（ParameterValue）：静态值 vs 引用其他节点输出
  - 分支连线 condition 的语义：on_success/on_error/true/false/regex

- 重要：create_workflow/update_workflow 的 nodes/connections 参数底层类型是 string（JSON 数组字符串）。
  - 本示例封装允许你直接传对象数组，封装层会自动 JSON.stringify。

- 推荐流程：
  1) 先 get_all_workflows 找到候选 workflow_id。
  2) 再 get_workflow 获取 nodes/connections 全量结构。
-  3) 如果你要“整体替换” nodes/connections：构造完整的新数组后用 update_workflow 一次性覆盖。
-  4) 如果你只想“增量修改” nodes/connections：优先使用 patch_workflow（node_patches/connection_patches）。

- 节点与连线的 ID：
  - 节点 id 可省略（服务端会生成），但如果你要创建 connections，强烈建议你在 nodes 里显式写好 id。
  - connections 里 source/target 可以用：
    - sourceNodeId/targetNodeId（推荐）
    - 或 source/target/from/to
    - 或 sourceIndex/targetIndex（按 nodes 数组下标）
    - 或 sourceNodeName/targetNodeName（不推荐：同名会歧义）

- 分支连线 condition（核心）：
  - 通用关键字（适用于任何节点类型）：
    - condition = "on_success" | "success" | "ok"：源节点成功时触发
    - condition = "on_error" | "error" | "failed"：源节点失败时触发（失败分支/补救逻辑）
  - 对 ConditionNode / LogicNode：
    - condition 为空：默认代表 true 分支（相当于 "true"）
    - condition = "false"：false 分支
    - condition = 其它字符串：当作 Regex 匹配源节点输出字符串
  - 对非 Condition/Logic 节点：
    - condition 为空：等价于 on_success（表示“源节点执行成功就走”）
    - condition = on_error：表示“源节点失败就走”（失败分支）

- 参数引用（ParameterValue）：
  - 静态值：直接写字符串/数字/布尔值即可（会被当作 StaticValue）
  - 引用某节点输出：写对象 { nodeId: "<node-id>" }
    - 兼容字段：nodeId / ref / refNodeId

- 触发节点类型（TriggerNode.triggerType）：
  - manual：手动触发（UI 点“触发工作流”）
  - schedule：定时触发（由 WorkManager 调度）
  - tasker：Tasker 事件触发
  - intent：系统广播 Intent 触发
  - speech：语音识别事件触发（当识别文本命中正则时触发；可多工作流同时触发）

  触发配置 TriggerNode.triggerConfig（注意：值全是 string）：
  - schedule：
    - schedule_type: interval | specific_time | cron
    - interval_ms: "900000"  (15分钟)
    - specific_time: "2026-01-04 10:30"  (格式依实现)
    - cron_expression: "15 * * * *"  (简化 cron)
    - repeat: "true"/"false"
    - enabled: "true"/"false"
  - tasker：
    - command: "start_meeting"  (当 Tasker params 中包含该字符串则触发)
  - intent：
    - action: "com.example.MY_ACTION"  (当收到该 action 的 Intent 则触发)
  - speech：
    - pattern: ".*(打开|启动).*(对话|聊天|悬浮窗).*"  (正则；匹配识别文本)
    - ignore_case: "true"/"false"  (可选，默认 true)
    - require_final: "true"/"false"  (可选，默认 true；true 表示仅 final 结果触发)
    - cooldown_ms: "3000"  (可选，默认 3000；每个节点的触发冷却)
'''
        en: '''
Workflow tool usage advice (for the AI):

- Core concepts (align your reasoning with these semantics):
  - Node types: trigger/execute/condition/logic/extract
  - Trigger node types: manual/schedule/tasker/intent/speech
  - Parameter references (ParameterValue): static values vs references to another node output
  - Connection "condition" meaning: on_success/on_error/true/false/regex

- Important: in create_workflow/update_workflow, nodes/connections are strings (JSON array strings) at the API layer.
  - This example wrapper lets you pass object arrays directly; it will JSON.stringify automatically.

- Recommended flow:
  1) Call get_all_workflows to find the candidate workflow_id.
  2) Call get_workflow to retrieve the full nodes/connections structure.
-  3) If you want to replace nodes/connections entirely: build the full new arrays and use update_workflow once to overwrite.
-  4) If you only want incremental changes: prefer patch_workflow (node_patches/connection_patches).

- Node and connection IDs:
  - Node id can be omitted (server will generate it), but if you need to create connections, strongly recommend explicitly setting node ids in nodes.
  - In connections, source/target can be provided as:
    - sourceNodeId/targetNodeId (recommended)
    - or source/target/from/to
    - or sourceIndex/targetIndex (index within nodes array)
    - or sourceNodeName/targetNodeName (not recommended: duplicates are ambiguous)

- Connection condition (core):
  - Global keywords (works for any node type):
    - condition = "on_success" | "success" | "ok": trigger when the source node succeeds
    - condition = "on_error" | "error" | "failed": trigger when the source node fails (error branch / recovery)
  - For ConditionNode / LogicNode:
    - empty condition: defaults to true branch (equivalent to "true")
    - condition = "false": false branch
    - other string: treated as a Regex to match the source node output string
  - For non-Condition/Logic nodes:
    - empty condition: equivalent to on_success (proceed if the source node succeeded)
    - condition = on_error: proceed if the source node failed (error branch)

- Parameter references (ParameterValue):
  - Static value: write a string/number/boolean directly (treated as StaticValue)
  - Reference another node output: write an object { nodeId: "<node-id>" }
    - compatible fields: nodeId / ref / refNodeId

- Trigger node types (TriggerNode.triggerType):
  - manual: manual trigger (tap "trigger workflow" in UI)
  - schedule: scheduled trigger (WorkManager)
  - tasker: triggered by Tasker events
  - intent: triggered by Android broadcast intents
  - speech: triggered by speech recognition events (fires when recognized text matches a regex; multiple workflows can match)

  Trigger configuration TriggerNode.triggerConfig (note: all values are strings):
  - schedule:
    - schedule_type: interval | specific_time | cron
    - interval_ms: "900000" (15 minutes)
    - specific_time: "2026-01-04 10:30" (format depends on implementation)
    - cron_expression: "15 * * * *" (simplified cron)
    - repeat: "true"/"false"
    - enabled: "true"/"false"
  - tasker:
    - command: "start_meeting" (triggered when Tasker params contains this string)
  - intent:
    - action: "com.example.MY_ACTION" (triggered when receiving this action)
  - speech:
    - pattern: ".*(open|start).*(chat|floating).*" (regex; matches recognized text)
    - ignore_case: "true"/"false" (optional, default true)
    - require_final: "true"/"false" (optional, default true; if true, only final results trigger)
    - cooldown_ms: "3000" (optional, default 3000; per-node cooldown)
'''
      }
      parameters: []
    }

    {
      name: "get_all_workflows"
      description: { zh: "获取所有工作流列表（只含概要信息：ID/名称/启用/统计等）。", en: "List all workflows (summary only: id/name/enabled/stats, etc.)." }
      parameters: []
    }

    {
      name: "get_workflow"
      description: { zh: "获取指定工作流完整详情（nodes + connections）。", en: "Get full details of a specific workflow (nodes + connections)." }
      parameters: [
        { name: "workflow_id", description: { zh: "工作流 ID", en: "Workflow ID" }, type: "string", required: true }
      ]
    }

    {
      name: "create_workflow"
      description: {
        zh: '''
创建工作流。

参数说明：
- nodes: JSON 数组字符串（推荐传对象数组，让封装自动 stringify）
- connections: JSON 数组字符串（同上）

节点类型（node.type）：
- trigger / execute / condition / logic / extract

Execute 节点：
- actionType: 工具名（如 "visit_web" / "list_files" / "get_system_setting" ...）
- actionConfig: 工具参数对象，支持 ParameterValue（静态值/节点引用）

Condition 节点：
- left/right: ParameterValue
- operator: EQ/NE/GT/GTE/LT/LTE/CONTAINS/NOT_CONTAINS/IN/NOT_IN

Logic 节点：
- operator: AND/OR

Extract（运算）节点：
- 说明：node.type 仍然是 "extract"（兼容旧数据），但语义更接近“运算器/计算节点”。
- source: ParameterValue（部分模式不需要，例如 RANDOM_INT）
- mode:
  - REGEX：正则提取
    - expression: 正则表达式
    - group/defaultValue 可选
  - JSON：JSON 路径提取
    - expression: JSON 路径（简化实现）
    - defaultValue 可选
  - SUB：字符串截取
    - startIndex: 起始下标
    - length: 长度（-1 表示到结尾）
    - defaultValue 可选
  - CONCAT：字符串拼接
    - others: ParameterValue[]（被拼接项列表）
  - RANDOM_INT：随机整数
    - randomMin/randomMax
    - useFixed: 是否使用固定值（可选）
    - fixedValue: 固定整数（可选，仅 useFixed=true 时生效；输出仍为数字字符串）
  - RANDOM_STRING：随机字符串
    - randomStringLength: 长度
    - randomStringCharset: 字符集（可选，默认字母数字）
    - useFixed: 是否使用固定值（可选）
    - fixedValue: 固定字符串（可选，仅 useFixed=true 时生效）
'''
        en: '''
Create a workflow.

Parameter notes:
- nodes: JSON array string (recommended: pass object arrays and let the wrapper stringify)
- connections: JSON array string (same as above)

Node types (node.type):
- trigger / execute / condition / logic / extract

Execute node:
- actionType: tool name (e.g. "visit_web" / "list_files" / "get_system_setting" ...)
- actionConfig: tool parameter object, supports ParameterValue (static value / node reference)

Condition node:
- left/right: ParameterValue
- operator: EQ/NE/GT/GTE/LT/LTE/CONTAINS/NOT_CONTAINS/IN/NOT_IN

Logic node:
- operator: AND/OR

Extract (operator) node:
- Note: node.type is still "extract" for backward compatibility, but it behaves like an "operator" node.
- source: ParameterValue (not required for some modes like RANDOM_INT)
- mode:
  - REGEX: regex extraction
    - expression: regex pattern
    - group/defaultValue are optional
  - JSON: JSON path extraction
    - expression: JSON path (simplified)
    - defaultValue optional
  - SUB: substring
    - startIndex
    - length (-1 means to end)
    - defaultValue optional
  - CONCAT: string concatenation
    - others: ParameterValue[]
  - RANDOM_INT: random integer
    - randomMin/randomMax
    - useFixed: whether to use a fixed value (optional)
    - fixedValue: fixed integer (optional, only effective when useFixed=true; output is still a numeric string)
  - RANDOM_STRING: random string
    - randomStringLength
    - randomStringCharset (optional, default: alphanumeric)
    - useFixed: whether to use a fixed value (optional)
    - fixedValue: fixed string (optional, only effective when useFixed=true)
'''
      }
      parameters: [
        { name: "name", description: { zh: "工作流名称", en: "Workflow name" }, type: "string", required: true }
        { name: "description", description: { zh: "工作流描述（可选）", en: "Workflow description (optional)" }, type: "string", required: false }
        { name: "nodes", description: { zh: "可选，节点 JSON 数组字符串（或直接传节点数组，由封装 stringify）", en: "Optional. Nodes JSON array string (or pass an array and the wrapper will stringify)." }, type: "string", required: false }
        { name: "connections", description: { zh: "可选，连线 JSON 数组字符串（或直接传连线数组，由封装 stringify）", en: "Optional. Connections JSON array string (or pass an array and the wrapper will stringify)." }, type: "string", required: false }
        { name: "enabled", description: { zh: "可选，是否启用（默认 true）", en: "Optional. Whether to enable (default: true)." }, type: "boolean", required: false }
      ]
    }

    {
      name: "update_workflow"
      description: {
        zh: '''
更新工作流。

注意：update_workflow 的 nodes / connections 是“整体覆盖”。
- 若你只改其中一部分，推荐使用 patch_workflow。
- 或者：get_workflow 取回旧结构 -> 本地构造新数组（保留未改部分）-> update_workflow 一次性传回。
'''
        en: '''
Update a workflow.

Note: nodes/connections in update_workflow are full overwrites.
- If you only change part of them, prefer patch_workflow.
- Or: call get_workflow to fetch the old structure -> build new arrays locally (keeping unchanged parts) -> call update_workflow once.
'''
      }
      parameters: [
        { name: "workflow_id", description: { zh: "工作流 ID", en: "Workflow ID" }, type: "string", required: true }
        { name: "name", description: { zh: "可选，新名称", en: "Optional. New name." }, type: "string", required: false }
        { name: "description", description: { zh: "可选，新描述", en: "Optional. New description." }, type: "string", required: false }
        { name: "nodes", description: { zh: "可选，节点 JSON 数组字符串（整体覆盖）", en: "Optional. Nodes JSON array string (full overwrite)." }, type: "string", required: false }
        { name: "connections", description: { zh: "可选，连线 JSON 数组字符串（整体覆盖）", en: "Optional. Connections JSON array string (full overwrite)." }, type: "string", required: false }
        { name: "enabled", description: { zh: "可选，是否启用", en: "Optional. Whether to enable." }, type: "boolean", required: false }
      ]
    }

    {
      name: "patch_workflow"
      description: {
        zh: '''
差异更新工作流（增量 patch）。

使用 node_patches / connection_patches 传入 JSON 数组字符串：
- op: add | update | remove
- id: 可选
- node / connection: 对象

说明：
- add：必须提供 node/connection
- update：必须提供 id 或 node.id/connection.id
- remove：必须提供 id
'''
        en: '''
Patch a workflow (incremental update).

Use node_patches / connection_patches as JSON array strings:
- op: add | update | remove
- id: optional
- node / connection: object

Notes:
- add: must provide node/connection
- update: must provide id OR node.id/connection.id
- remove: must provide id
'''
      }
      parameters: [
        { name: "workflow_id", description: { zh: "工作流 ID", en: "Workflow ID" }, type: "string", required: true }
        { name: "name", description: { zh: "可选，新名称", en: "Optional. New name." }, type: "string", required: false }
        { name: "description", description: { zh: "可选，新描述", en: "Optional. New description." }, type: "string", required: false }
        { name: "enabled", description: { zh: "可选，是否启用", en: "Optional. Whether to enable." }, type: "boolean", required: false }
        { name: "node_patches", description: { zh: "可选，节点 patch JSON 数组字符串", en: "Optional. Node patch JSON array string." }, type: "string", required: false }
        { name: "connection_patches", description: { zh: "可选，连线 patch JSON 数组字符串", en: "Optional. Connection patch JSON array string." }, type: "string", required: false }
      ]
    }

    {
      name: "enable_workflow"
      description: { zh: "启用指定工作流。", en: "Enable a specific workflow." }
      parameters: [
        { name: "workflow_id", description: { zh: "工作流 ID", en: "Workflow ID" }, type: "string", required: true }
      ]
    }

    {
      name: "disable_workflow"
      description: { zh: "禁用指定工作流。", en: "Disable a specific workflow." }
      parameters: [
        { name: "workflow_id", description: { zh: "工作流 ID", en: "Workflow ID" }, type: "string", required: true }
      ]
    }

    {
      name: "delete_workflow"
      description: { zh: "删除指定工作流。", en: "Delete a specific workflow." }
      parameters: [
        { name: "workflow_id", description: { zh: "工作流 ID", en: "Workflow ID" }, type: "string", required: true }
      ]
    }

    {
      name: "trigger_workflow"
      description: { zh: "触发指定工作流执行（相当于 UI 手动触发）。", en: "Trigger execution of a workflow (equivalent to manual trigger in UI)." }
      parameters: [
        { name: "workflow_id", description: { zh: "工作流 ID", en: "Workflow ID" }, type: "string", required: true }
      ]
    }
  ]
}*/
"""
    }

    @Test
    fun automatic_ui_subagent_metadata_is_hjson() {
        val parsed = runtime.parseMetadata(AUTOMATIC_UI_SUBAGENT)
        assertNotNull("the block did not parse at all", parsed)
        assertEquals("Automatic_ui_subagent", parsed!!.optString("name"))
    }

    @Test
    fun code_runner_metadata_is_hjson() {
        val parsed = runtime.parseMetadata(CODE_RUNNER)
        assertNotNull("the block did not parse at all", parsed)
        assertEquals("code_runner", parsed!!.optString("name"))
    }

    @Test
    fun operit_editor_metadata_is_hjson() {
        val parsed = runtime.parseMetadata(OPERIT_EDITOR)
        assertNotNull("the block did not parse at all", parsed)
        assertEquals("operit_editor", parsed!!.optString("name"))
    }

    @Test
    fun time_metadata_is_hjson() {
        val parsed = runtime.parseMetadata(TIME)
        assertNotNull("the block did not parse at all", parsed)
        assertEquals("time", parsed!!.optString("name"))
    }

    @Test
    fun various_search_metadata_is_hjson() {
        val parsed = runtime.parseMetadata(VARIOUS_SEARCH)
        assertNotNull("the block did not parse at all", parsed)
        assertEquals("various_search", parsed!!.optString("name"))
    }

    @Test
    fun workflow_metadata_is_hjson() {
        val parsed = runtime.parseMetadata(WORKFLOW)
        assertNotNull("the block did not parse at all", parsed)
        assertEquals("workflow", parsed!!.optString("name"))
    }
}
