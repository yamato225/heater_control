import concurrent.futures
import time
import os
import re
import pigpio
from multiprocessing import Process, Value

# Defines
ONEWIRE_PATH="/sys/bus/w1/devices"
SENSOR_LABELS={"28-3c01a8169133":"heater","28-3c01a816d9f0":"water"}
GPIO_PULSE1=16
GPIO_ENABLE1=12
TARGET_TEMP=41


def read_temp_file(file_name):
    #print("start to read:"+file_name)
    with open(ONEWIRE_PATH+"/"+file_name+"/w1_slave") as f:
        temp=0
        try:
            temp=int(re.findall('.*t=([0-9]+)$',f.read()).pop())/1000
        except Exception as exc:
            temp=0
        return temp

def get_temp_list(labels):
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
    pulse=0
    pi=pigpio.pi()

    #pi.write(GPIO_ENABLE1,1)
    #time.sleep(1)
    pi.set_mode(GPIO_ENABLE1,pigpio.OUTPUT)
    pi.set_mode(GPIO_PULSE1,pigpio.OUTPUT)
    pi.write(GPIO_ENABLE1,1)
    while True:
        if st.value > 0:
            # ヒーター作動
            st.value -= 1
            pulse=1-pulse
            pi.write(GPIO_PULSE1,pulse)
        time.sleep(0.01)

def monitor_temp(st: Value):
    zero_count=0

    while True:
        temp_list=get_temp_list(SENSOR_LABELS)
        print(sorted(temp_list.items(),key=lambda x:x[0]))
        if temp_list['water']<TARGET_TEMP:
            st.value=200
        else:
            st.value=0
        if temp_list['water'] == 0 or temp_list['heater'] == 0:
            zero_count+=1
        else:
            zero_count=0
        if temp_list['heater']>60 or zero_count>3:
            st.value=0


def main():
    shared_time = Value('i', 0)
    control_process=Process(target=control_heater,args=(shared_time,))
    control_process.start()
    monitor_process=Process(target=monitor_temp,args=(shared_time,))
    monitor_process.start()



if __name__ == "__main__":
    main()
