import concurrent.futures
import time
import os
import re
import pigpio
from multiprocessing import Process, Value
import sys

from linebot import LineBotApi
from linebot.models import TextSendMessage
from linebot.exceptions import LineBotApiError

# Defines
ONEWIRE_PATH="/sys/bus/w1/devices"
SENSOR_LABELS={"28-3c01a8169133":"heater","28-3c01a816d9f0":"water","28-3c01d607f380":"heater2",}
GPIO_PULSE1=16
GPIO_ENABLE1=12
TARGET_TEMP=40.5
AVG_NUM=30
MAX_TIME=12
HEATER_TEST_DURATION=30
HEATER_ERROR_THRESHOLD=10
MAX_DIFF_THRESHOLD=6
HEATER_MAX_TEMP=65
#環境変数取得
YOUR_CHANNEL_ACCESS_TOKEN = os.environ["YOUR_CHANNEL_ACCESS_TOKEN"]
LINE_NOTICE_TARGET = os.environ["LINE_NOTICE_TARGET"]

def read_temp_file(file_name):
    ##
    # @brief 指定された1-wire温度センサの値を取得する。
    # @param file_name デバイス名(/sys/bus/w1/devices以下のディレクトリ名)
    with open(ONEWIRE_PATH+"/"+file_name+"/w1_slave") as f:
        temp=0
        try:
            temp=int(re.findall('.*t=([0-9]+)$',f.read()).pop())/1000
        except Exception as exc:
            temp=0
        return temp

def get_temp_list(labels):
    ##
    # @brief 温度取得関数
    # @details 指定された1-wire温度センサの値を取得する。
    # @param labels 1-wireデバイス名をキー、そのセンサーの値の名称を値としたdict
    result={}
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_list={executor.submit(read_temp_file,dev_name): dev_name for dev_name in list(labels.keys())}
        for future in concurrent.futures.as_completed(future_list):
            dev_name=future_list[future]
            try:
                result[labels[dev_name]]=future.result()
            except Exception as exc:
                pass

    return result

def control_heater(st: Value):
    ##
    # @brief ヒーター制御関数
    # @details 立ち下がりパルスを与えてヒーターを作動させる。
    # @param st ヒーター作動時間(0.01秒単位)
    pulse=0
    pi=pigpio.pi()

    pi.set_mode(GPIO_ENABLE1,pigpio.OUTPUT)
    pi.set_mode(GPIO_PULSE1,pigpio.OUTPUT)
    pi.write(GPIO_ENABLE1,1)
    while True:
        if st.value > 0:
            # ヒーターを指定された時間だけ作動。
            st.value -= 1
            pulse=1-pulse
            # 0.01秒毎に立ち下がりパルスを与える。
            pi.write(GPIO_PULSE1,pulse)
        time.sleep(0.01)

def monitor_temp(st: Value):
    ##
    # @brief 温度監視関数(プロセス)
    # @details 温度を監視しヒータを操作する。
    # @param st ヒーター作動時間(0.01秒単位)

    zero_count=0

    # 監視開始時刻を確認する。
    start_time=time.time()
    last_time=start_time
    ontime=0
    total_time=0
    max_temp=0
    old_max_temp=0

    #平均温度
    avg_temp=0.0
    temp_array=list()
    heater_array=list()

    # LINE BOT初期化
    line_bot_api=LineBotApi(YOUR_CHANNEL_ACCESS_TOKEN)

    try:
        #pass
        line_bot_api.push_message(LINE_NOTICE_TARGET, TextSendMessage(text='加熱開始'))
    except LineBotApi as e:
        print("Failed to initialize LINE API")
        return -1

    t=0
    is_noticed=False
    while True:
        temp_list=get_temp_list(SENSOR_LABELS)
        # 正常処理
        wt=temp_list['water']
        if wt>0:
            temp_array.append(wt)
        if len(temp_array)>AVG_NUM:
            temp_array.pop(0)
        if len(temp_array)>0:
            avg_temp=sum(temp_array)/len(temp_array)
        if avg_temp<TARGET_TEMP:
            t=300
        else:
            t=0
        # 異常処理
        ## 温度取得に10回連続で失敗したら終了
        if len([x for x in temp_list.values() if x < 1])>0:
            zero_count+=1
            if zero_count>10:
                msg="センサー異常発生"
                break
        else:
            zero_count=0
        ## センサー温度が60度を超えたら終了
        max_temp=max(temp_list.values())
        if max_temp > HEATER_MAX_TEMP:
            msg="異常加熱発生"
            break
        ## 温度が急激に上昇した場合はヒーターを停止する。
        if (max_temp - old_max_temp)>MAX_DIFF_THRESHOLD:
            t=0
        old_max_temp=max_temp
        temp_ratio=max(temp_list.values())/avg_temp 
        st.value=t
        ## 開始からMAX_TIME時間経過したら終了
        current_time=time.time()
        total_time=current_time-start_time
        if total_time > MAX_TIME*3600:
            msg="時間切れ"
            break
        if t>0:
            ontime+=current_time - last_time
        last_time=current_time
        temp_msg=str(sorted(temp_list.items(),key=lambda x:x[0]))
        #if (round(total_time,0) % 600)==0:
        #    line_bot_api.push_message(LINE_NOTICE_TARGET, TextSendMessage(text='水温:'+str(avg_temp)))

        if total_time>30 and is_noticed == False and avg_temp >= TARGET_TEMP:
            line_bot_api.push_message(LINE_NOTICE_TARGET, TextSendMessage(text='お風呂が沸きました。'))
            is_noticed=True
        # 動作状態表示
        print(str(round(avg_temp,1))+" run:"+str(round(total_time/60,1))+" on:"+str(round(ontime/60,1))+" "+temp_msg+",st="+str(st.value)+",r="+str(round(temp_ratio,1)))
        time.sleep(0.5)

    line_bot_api.push_message(LINE_NOTICE_TARGET, TextSendMessage(text=msg))
    return -1


def main():
    ##
    # @brief メイン関数
    # @details ヒーター制御関数と温度監視関数を別プロセスで起動する。
    shared_time = Value('i', 0)
    control_process=Process(target=control_heater,args=(shared_time,))
    control_process.start()
    monitor_process=Process(target=monitor_temp,args=(shared_time,))
    monitor_process.start()
    sys.exit(0)



if __name__ == "__main__":
    if(len(sys.argv)>=2):
        time.sleep(int(sys.argv[1]))
    main()
