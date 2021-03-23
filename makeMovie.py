from moviepy.editor import VideoFileClip,ImageSequenceClip
import cv2
import copy
import os
import numpy as np
from frvtPythonWrapper import FRVTWrapper,FRVTLibraryLoader,FRVTImage,FRVTMultiface
import multiprocessing
from multiprocessing import Process
from typing import Sequence
import shutil
from pytube import YouTube
import re


class AlgorithmInfo:
    def __init__(self,algorithmName=None,edbDir=None,implDir=None,libName=None,enrollmentDir=None):
        self.algorithmName = algorithmName
        self.edbDir = edbDir
        self.implDir = implDir 
        self.libName = libName
        self.enrollmentDir = enrollmentDir
        self.configDir = os.path.join(self.implDir,"config")
        self.libDir = os.path.join(self.implDir,"lib")
        

def codeTemplatesForSubClip(moviePath,startTime,endTime,fps,algoInfo:AlgorithmInfo,templateOutputFolder=None):
    templateOutputPathForAlgorithm = os.path.join(templateOutputFolder,algoInfo.algorithmName)
    if not os.path.exists(templateOutputPathForAlgorithm):
        os.makedirs(templateOutputPathForAlgorithm)
    libraryLoader = FRVTLibraryLoader()
    libraryLoader.loadLibrary(algoInfo.libName,libDir=algoInfo.libDir)
    wrapper = FRVTWrapper(libraryLoader)
    wrapper.initializeTemplateCreation()
    clip = VideoFileClip(moviePath).subclip(startTime,endTime)
    startFrameNumber = int(fps * startTime)
    currentFrameNumber = startFrameNumber
    for currentFrame in clip.iter_frames(fps):
        filename_template = str(currentFrameNumber).zfill(5)+".template"
        filename_eyes = str(currentFrameNumber).zfill(5)+".eyes"
        fullFilename_template = os.path.join(templateOutputPathForAlgorithm,filename_template)
        fullFilename_eyes = os.path.join(templateOutputPathForAlgorithm,filename_eyes)
        #moviepy gives us the image in RGB, so we dont have to switch
        frvtImage = FRVTImage(libraryLoader,currentFrame,switchColorChannelsToRGB=False)
        multiFace = FRVTMultiface(libraryLoader,frvtImage)
        (retCode,templateData,isLeftAssigned,isRightAssigned,leftX,rightX,leftY,rightY) = wrapper.encodeTemplate(multiFace)
        if retCode == 0:
            fileHandle_eyes = open(fullFilename_eyes,"w")
            fileHandle_eyes.write(f"{isLeftAssigned} {isRightAssigned} {leftX} {rightX} {leftY} {rightY}")
            fileHandle_eyes.close()
            templateData.tofile(fullFilename_template)
        currentFrameNumber +=1

class MovieMaker:
    def __init__(self,algoInfos: Sequence[AlgorithmInfo], referenceImagePaths: Sequence[str], inputFolder = "movieInput"):
        self.inputFolder = inputFolder
        if not os.path.exists(self.inputFolder):
            os.makedirs(self.inputFolder)
        self.algoInfos = algoInfos
        self.templateOutputFolder = "templates"
        self.frameOutputFolder = "frames"
        self.referenceImagePaths = referenceImagePaths


    def findEdbsForAlgorithm(self,algoInfo:AlgorithmInfo):
        edbFiles = filter(lambda x: x.endswith(".edb"),os.listdir(algoInfo.edbDir))
        edbFiles_full = [os.path.join(algoInfo.edbDir,x) for x in edbFiles]
        return edbFiles_full

        

    def makeMovie(self,moviePath:str,outputFolder="/frvtMovieMaker/"):
        self.movieOutputFolder = os.path.join(outputFolder,"outputMovie")
        if not os.path.exists(self.movieOutputFolder):
            os.makedirs(self.movieOutputFolder)

        cpuCount = multiprocessing.cpu_count()

        eyeColors = [(0,0,255), (255,0,0)]

        regex_url = re.compile(
        r'^(?:http|ftp)s?://' # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' #domain...
        r'localhost|' #localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' # ...or ip
        r'(?::\d+)?' # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
        #encode referenceImage
        if re.match(regex_url,moviePath) is not None:
            if 'youtube' in moviePath:
                print("Downloading video...")
                yt = YouTube(moviePath)
                yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first().download(output_path=self.inputFolder)
                moviePath = list(filter(lambda x: x.endswith(".mp4"),os.listdir(self.inputFolder)))[0]
                moviePath = os.path.join(self.inputFolder,moviePath)

               
            else:
                print("Please provide a valid youtube link or file path")
        

        clip = VideoFileClip(moviePath)
        secondsPerWorker = clip.duration/cpuCount


        self.templateOutputFolder = os.path.join(outputFolder,"templates")
        if not os.path.exists(self.templateOutputFolder):
            os.makedirs(self.templateOutputFolder)
            #code templates by multiprocessing
            for currentAlgoInfo in self.algoInfos:
                startTime = 0
                processList = []
                for currentWokerIndex in range(cpuCount):
                    endTime = min(startTime + secondsPerWorker,clip.duration)
                    #codeTemplatesForSubClip(moviePath,startTime,endTime,clip.fps,self.libdir,self.libname)
                    p = Process(target = codeTemplatesForSubClip, args =(moviePath,startTime,endTime,clip.fps,currentAlgoInfo), kwargs={"templateOutputFolder":self.templateOutputFolder})
                    p.start()
                    print(f"Starting worker with start time {startTime} and end time {endTime}")
                    processList.append(p)
                    startTime = endTime
            for currentProcess in processList:
                currentProcess.join()
        else:
            print("Using existing template folder")
        
        self.frameOutputFolder =  os.path.join(outputFolder,"frames")
        if not os.path.exists(self.frameOutputFolder):
            os.makedirs(self.frameOutputFolder)
            self.referenceImageDict = {}
            for referenceImageIndex,referenceImagePath in enumerate(self.referenceImagePaths):
                referenceImage = cv2.imread(referenceImagePath)
                self.referenceImageDict[f"ref_{referenceImageIndex}"] = referenceImage


            #iterate over all algorithms and edbs and generate a hitlist for each algo/edb setting
            for currentAlgoIndex,currentAlgoInfo in enumerate(self.algoInfos):
                currentEyeColor = eyeColors[currentAlgoIndex]
                templateFolderForAlgo = os.path.join(self.templateOutputFolder,currentAlgoInfo.algorithmName)
                libraryLoader = FRVTLibraryLoader()
                libraryLoader.loadLibrary(currentAlgoInfo.libName,libDir=currentAlgoInfo.libDir)
                wrapper = FRVTWrapper(libraryLoader)
                wrapper.initializeTemplateCreation()
                referenceTemplates = []
                for referenceImage in self.referenceImageDict.values():
                    frvtImage = FRVTImage(libraryLoader,referenceImage)
                    multiFace = FRVTMultiface(libraryLoader,frvtImage)
                    (retCode,templateData,isLeftAssigned,isRightAssigned,leftX,rightX,leftY,rightY) = wrapper.encodeTemplate(multiFace)
                    if retCode == 0:
                        print("Reference image successfully enrolled")
                    else:
                        print("Enrollment of reference image was not successful!")
                        raise RuntimeError("Enrollment of reference image failed!")
                    referenceTemplates.append(templateData)
                edbs = self.findEdbsForAlgorithm(currentAlgoInfo)
                for currentEdb in edbs:
                    print(f"Processing edb {currentEdb}")
                    currentManifestFile = os.path.splitext(currentEdb)[0]+".manifest"
                    if not os.path.exists(currentAlgoInfo.enrollmentDir):
                        print("Enrollment dir does not exist. Creating it...")
                        os.makedirs(currentAlgoInfo.enrollmentDir)
                    retCode = wrapper.finalizeEnrolment(currentAlgoInfo.configDir,currentAlgoInfo.enrollmentDir,currentEdb,currentManifestFile, 0)
                    print(f"Finalize enrollment returned ret code {retCode}")
                    retCode = wrapper.initializeIdentification(currentAlgoInfo.configDir,currentAlgoInfo.enrollmentDir)
                    print(f"Initialize identification returned ret code {retCode}")
                    for templateIndex,templateData in enumerate(referenceTemplates):
                        wrapper.insertTemplate(templateData, f"ref_{templateIndex}")
                    self.placeholderImage = cv2.imread("placeholder.jpg")

                    currentFrameNumber = 0
                    for currentFrame in clip.iter_frames(clip.fps):
                        currentFrameNumberAsString = str(currentFrameNumber).zfill(5)
                        frameName = os.path.join(self.frameOutputFolder,currentFrameNumberAsString+".jpg")
                        templateFile = currentFrameNumberAsString+".template"
                        templateFile_full = os.path.join(templateFolderForAlgo,templateFile)
                        eyesFile = currentFrameNumberAsString + ".eyes"
                        eyesFile_full = os.path.join(templateFolderForAlgo,eyesFile)
                        copiedFrame = copy.copy(currentFrame)
                        copiedFrame_bgr = copiedFrame[:,:,::-1]
                        copiedFrame_bgr = np.array(copiedFrame_bgr)
                        if os.path.exists(templateFile_full):
                            templateData = np.fromfile(templateFile_full,dtype=np.int8)

                            candidateList,decisionValue = wrapper.identifyTemplate(templateData,10)
                            #check if already a frame exists and add the new hitlist in this case
                        
                            if os.path.exists(frameName):
                                frameToUse = cv2.imread(frameName)
                                imageWithHitList = self.drawHitListToImage(frameToUse,candidateList.toList(),currentAlgoInfo.algorithmName,currentEdb)
                            else:
                                imageWithHitList = self.drawHitListToImage(copiedFrame_bgr,candidateList.toList(),currentAlgoInfo.algorithmName,currentEdb)

                            eyeFileHandle = open(eyesFile_full,"r")
                            firstLine = eyeFileHandle.readline()
                            firstLine_splitted = firstLine.split(" ")
                            eyeFileHandle.close()
                            #draw eyes if they are assigned
                            if bool(firstLine_splitted[0]):
                                leftX = int(firstLine_splitted[2])
                                rightX = int(firstLine_splitted[3])
                                leftY = int(firstLine_splitted[4])
                                rightY = int(firstLine_splitted[5])
                                imageWithHitList = cv2.circle(imageWithHitList, (leftX,leftY), 3,  currentEyeColor,-1)
                                imageWithHitList = cv2.circle(imageWithHitList, (rightX,rightY), 3,  currentEyeColor,-1)
                            #save frame
                            cv2.imwrite(frameName,imageWithHitList)
                        else:
                            if os.path.exists(frameName):
                                frameToUse = cv2.imread(frameName)
                                enlargedImage = cv2.copyMakeBorder(frameToUse, 0, 200, 0, 0, cv2.BORDER_CONSTANT, None, (255,255,255))
                            else:
                                enlargedImage = cv2.copyMakeBorder(copiedFrame_bgr, 0, 200, 0, 0, cv2.BORDER_CONSTANT, None, (255,255,255))
                            #save frame
                            cv2.imwrite(frameName,enlargedImage)
                        currentFrameNumber +=1
        else:
            print("Using existing frame folder")
        framesToCombine = [os.path.join(self.frameOutputFolder,x) for x in os.listdir(self.frameOutputFolder)]
        newClip = ImageSequenceClip(framesToCombine,fps=clip.fps)
        newClip = newClip.set_audio(clip.audio)
        newClip.write_videofile(os.path.join(self.movieOutputFolder,"output.mp4"))
        shutil.rmtree(self.frameOutputFolder)
        shutil.rmtree(self.templateOutputFolder)
        shutil.rmtree(self.inputFolder)
        
    def drawHitListToImage(self,image,hitlist,algoName, edbName):
       
        enlargedImage = cv2.copyMakeBorder(image, 0, 200, 0, 0, cv2.BORDER_CONSTANT, None, (255,255,255))

        #write algorithm name

        font                   = cv2.FONT_HERSHEY_SIMPLEX
        bottomLeftCornerOfText = (10,image.shape[0]+ 30)
        fontScale              = 0.5
        fontColor              = (0,0,0)
        lineType               = 2

        cv2.putText(enlargedImage,"Algorithm: "+algoName+" Edb: "+os.path.basename(edbName), bottomLeftCornerOfText, font, fontScale,fontColor,lineType)

        bottomOffset = 50
        leftOffset = 20
        spacing = 20
        hitlistImageWidth = int((enlargedImage.shape[1] - 10*spacing)/10)
        hitlistImageHeight = min(130,hitlistImageWidth)

        for key in self.referenceImageDict:
            self.referenceImageDict[key] = cv2.resize(self.referenceImageDict[key], (hitlistImageWidth,hitlistImageHeight))

        placeholder_resized = cv2.resize(self.placeholderImage, (hitlistImageWidth,hitlistImageHeight))

        startX = leftOffset
        startY = enlargedImage.shape[0] - bottomOffset - hitlistImageHeight
        endY = enlargedImage.shape[0] - bottomOffset

        for candidate in hitlist:
            if candidate.templateId in self.referenceImageDict:
                 enlargedImage[startY:endY,startX:startX+hitlistImageWidth,:] = self.referenceImageDict[candidate.templateId]
            else:
                 enlargedImage[startY:endY,startX:startX+hitlistImageWidth,:] = placeholder_resized
            
            startX += hitlistImageWidth + spacing

        return enlargedImage



if __name__ == '__main__':
    #points to location of frvt implementation (containing lib and config dirs)
    baseDir = "/frvtMovieMaker/"

    referenceImagePath1 = "schwarzenegger.jpg"
    referenceImagePath2 = "schwarzenegger2.jpg"

    referenceImagePaths = [referenceImagePath1,referenceImagePath2]

    moviePath = "https://www.youtube.com/watch?v=HvyUnZNE6yc"
    algoInfo1 = AlgorithmInfo("Dermalog008",os.path.join(baseDir,"edbs"),implDir = baseDir,libName = "libfrvt_1N_dermalog_008.so", enrollmentDir=os.path.join(baseDir,"enroll"))
    #gets a list of algorithm infos and a list of reference images
    myMoviemaker = MovieMaker([algoInfo1],referenceImagePaths)
    myMoviemaker.makeMovie(moviePath)
 
