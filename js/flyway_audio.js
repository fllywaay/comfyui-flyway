import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

app.registerExtension({
    name: "flyway.audio_player",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        // 在这里填入你所有需要显示音频播放器的节点名称
        const targetNodes =[
            "FlywayAudioSave", 
            "FlywayFishAudioAlign", 
            "FlywayTranslateAndAlign",
            "FlywayAudioTimeAlign"
        ];
        
        if (targetNodes.includes(nodeData.name)) {
            const onExecuted = nodeType.prototype.onExecuted;
            
            nodeType.prototype.onExecuted = function (message) {
                // 调用原本的 onExecuted（如果有）
                if (onExecuted) {
                    onExecuted.apply(this, arguments);
                }

                // 清理旧的音频播放器（防止多次点击运行后，播放器越叠越多）
                if (this.widgets) {
                    const pos = this.widgets.findIndex((w) => w.name === "audio_player");
                    if (pos !== -1) {
                        for (let i = pos; i < this.widgets.length; i++) {
                            if (this.widgets[i].onRemove) {
                                this.widgets[i].onRemove();
                            }
                        }
                        this.widgets.length = pos;
                    }
                }

                // 如果后端返回了 audio 数据，则创建 HTML 播放器
                if (message && message.audio) {
                    message.audio.forEach((params) => {
                        // 拼接请求音频文件的 URL
                        const url = api.apiURL('/view?' + new URLSearchParams(params).toString());
                        
                        // 创建原生的 audio 标签
                        const audioEl = document.createElement("audio");
                        audioEl.controls = true;
                        audioEl.src = url;
                        audioEl.style.width = "100%";
                        audioEl.style.marginTop = "5px";
                        
                        // 将 audio 标签作为 DOM Widget 添加到节点上
                        const widget = this.addDOMWidget("audio_player", "audio", audioEl, {
                            serialize: false,
                            hideOnZoom: false,
                        });
                        
                        // 设置播放器的高度
                        widget.computeSize = function(width) {
                            return [width, 50];
                        };
                    });
                    
                    // 强制刷新节点大小，让播放器显示出来
                    this.setSize(this.computeSize());
                    app.graph.setDirtyCanvas(true, true);
                }
            };
        }
    }
});