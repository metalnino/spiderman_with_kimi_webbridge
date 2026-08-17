function performSearchRequest(tokenData) {
	
	var tenderBulletinParams = getSearchParams();
	var industrySearchValue = "";//行业
	var areaSearchValue = "";//地区
	var platFormSearchValue = "";//平台
	var keySearchValue = "";//搜索框的内容
	var businessType = "";//右侧tab页业务标题
	var searchTimeStart = "";//评标公示,中标公告两个tab的查询开始时间
	var searchTimeStop = "";//评标公示,中标公告两个tab的查询结束时间
	var timeTypeParam = "";
	var bulletinIssnTime = "";//招标公告发布时间
	var bulletinIssnTimeStart = "";//招标公告结束时间起点
	var bulletinIssnTimeStop = "";//招标公告结束时间截止
	industrySearchValue = tenderBulletinParams[0];
	if(null!=industrySearchValue&&""!=industrySearchValue&&undefined!=industrySearchValue){
		industrySearchValue = industrySearchValue.substring(0,industrySearchValue.length-1);
	}
	areaSearchValue = tenderBulletinParams[1];
	if(null!=areaSearchValue&&""!=areaSearchValue&&undefined!=areaSearchValue){
		areaSearchValue = areaSearchValue.substring(0,areaSearchValue.length-1);
	}
	if(null!=tenderBulletinParams[2]&&""!=tenderBulletinParams[2]&&undefined!=tenderBulletinParams[2]){
		platFormSearchValue = "transactionPlatfCode:"+tenderBulletinParams[2];
	}
	keySearchValue = tenderBulletinParams[3];
	
	if($("#myTab_Contenta0").css("display") == "block"){
		businessType = "招标公告";
		//第一个输入框
		var input1 = $("#bulletinIssnTime").val();
		//第二个输入框
		var input2 = $("#tenderBulletin_selected").val();
		var bulletinBeginTime = $("#bulletinBeginTime").val();//公告发布开始时间起点
		var bulletinBeginTime1 = $("#bulletinBeginTime1").val();//公告发布开始时间截止
		if(null != bulletinBeginTime1 && '' != bulletinBeginTime1){
			var arr1 = bulletinBeginTime1.split("-");  
			var date = new Date(arr1[0],parseInt(arr1[1])-1,arr1[2]);
			date.setDate(date.getDate()+1);
			var month = date.getMonth()+1;
			var day = date.getDate();
			bulletinBeginTime1 =  date.getFullYear() + '-' + getFormatDate(month) + '-' + getFormatDate(day);
		}
		var bulletinEndTime = $("#bulletinEndTime").val();//公告结束时间起点
		var bulletinEndTime2 = $("#bulletinEndTime2").val();//公告结束时间截止
		if(input1 != "" && input1 != null){//公告发布时间
			if(bulletinBeginTime !="" || bulletinBeginTime1 !=""){
				bulletinIssnTimeStart = bulletinBeginTime;
				bulletinIssnTimeStop = bulletinBeginTime1;
			}else{
				//第一个输入框的值
				bulletinIssnTime = $("#bulletinIssnTime").val();
			}
		}else if(input2 != "" && input2 != null){//公告结束时间
			if(bulletinEndTime !="" || bulletinEndTime2 !=""){
				searchTimeStart = bulletinEndTime;
				searchTimeStop = bulletinEndTime2;
			}else{
				//第二个输入框的值
				bulletinIssnTime = $("#tenderBulletin_selected").val();
			}
		}else{//查询全部
			
		}
//		searchTimeStart = $("#bidOpen").val();
//		searchTimeStop = $("#bidEnd").val();
//		if((null == searchTimeStart || "" == searchTimeStart )&& (null == searchTimeStop || "" == searchTimeStop)){			
//			timeTypeParam = $("#openBidRecord_DateTimeSearch").val();
//		}
//		timeTypeParam = $("#tenderBulletin_selected").val();
	}else if($("#myTab_Contenta1").css("display") == "block"){
		businessType = "开标记录";
		searchTimeStart = $("#bidOpen").val();
		searchTimeStop = $("#bidEnd").val();
		if(null != searchTimeStop && '' != searchTimeStop){
			var arr1 = searchTimeStop.split("-");  
			var date = new Date(arr1[0],parseInt(arr1[1])-1,arr1[2]);
			date.setDate(date.getDate()+1);
			var month = date.getMonth()+1;
			var day = date.getDate();
			searchTimeStop =  date.getFullYear() + '-' + getFormatDate(month) + '-' + getFormatDate(day);
		}
		if((null == searchTimeStart || "" == searchTimeStart )&& (null == searchTimeStop || "" == searchTimeStop)){			
			timeTypeParam = $("#openBidRecord_DateTimeSearch").val();
		}
	}else if($("#myTab_Contenta2").css("display") == "block"){
		businessType = "评标公示";
		searchTimeStart = $("#evaluationBidBegin").val();
		searchTimeStop = $("#evaluationBidEnd").val();
		if(null != searchTimeStop && '' != searchTimeStop){
			var arr1 = searchTimeStop.split("-");  
			var date = new Date(arr1[0],parseInt(arr1[1])-1,arr1[2]);
			date.setDate(date.getDate()+1);
			var month = date.getMonth()+1;
			var day = date.getDate();
			searchTimeStop =  date.getFullYear() + '-' + getFormatDate(month) + '-' + getFormatDate(day);
		}
		if((null == searchTimeStart || "" == searchTimeStart )&& (null == searchTimeStop || "" == searchTimeStop)){			
			timeTypeParam = $("#bidEvaluation_DateTimeSearch").val();
		}
	}else if($("#myTab_Contenta3").css("display") == "block"){
		businessType = "中标公告";
		searchTimeStart = $("#winBidBegin").val();
		searchTimeStop = $("#winBidEnd").val();
		if(null != searchTimeStop && '' != searchTimeStop){
			var arr1 = searchTimeStop.split("-");  
			var date = new Date(arr1[0],parseInt(arr1[1])-1,arr1[2]);
			date.setDate(date.getDate()+1);
			var month = date.getMonth()+1;
			var day = date.getDate();
			searchTimeStop =  date.getFullYear() + '-' + getFormatDate(month) + '-' + getFormatDate(day);
		}
		if((null == searchTimeStart || "" == searchTimeStart )&& (null == searchTimeStop || "" == searchTimeStop)){			
			timeTypeParam = $("#winBidBulletin_DateTimeSearch").val();
		}
	}/*else if($("#myTab_Contenta5").css("display") == "block"){
		businessType = "招标项目";
		searchTimeStart = $("#projectBeginTime").val();
		searchTimeStop = $("#projectEndTime").val();
		if(null != searchTimeStop && '' != searchTimeStop){
			var arr1 = searchTimeStop.split("-");  
			var date = new Date(arr1[0],parseInt(arr1[1])-1,arr1[2]);
			date.setDate(date.getDate()+1);
			var month = date.getMonth()+1;
			var day = date.getDate();
			searchTimeStop =  date.getFullYear() + '-' + getFormatDate(month) + '-' + getFormatDate(day);
		}
		if((null == searchTimeStart || "" == searchTimeStart )&& (null == searchTimeStop || "" == searchTimeStop)){			
			timeTypeParam = $("#tenderProject_DateTimeSearch").val();
		}
	}*/
	const requestData = {
        // 业务参数
        searchName: keySearchValue,
        searchArea: areaSearchValue,
        searchIndustry: industrySearchValue,
        centerPlat: platFormSearchValue,
        businessType: businessType,
        searchTimeStart: searchTimeStart,
        searchTimeStop: searchTimeStop,
        timeTypeParam: timeTypeParam,
        bulletinIssnTime: bulletinIssnTime,
        bulletinIssnTimeStart: bulletinIssnTimeStart,
        bulletinIssnTimeStop: bulletinIssnTimeStop,
        pageNo: pageNo,
        row: row
    };
	debugger
    // ✅ 如果有 tokenData，带上验证信息
    if (tokenData) {
        requestData.token = tokenData.token;
        requestData.knock = tokenData.knock;
        requestData.dfu = tokenData.dfu;
    }
	$.ajax({
		type : 'post',
		url : path+'/searchbusinesstypebeforedooraction/getStringMethod.do',
		data : requestData,
		dataType : "json",
		async:false,
		success : function(data) {
			
			if(data.success){
				if(data.object != null){
					count = data.object.page.totalCount;
				}else{
					count = 0;
				}
				if(businessType =="招标公告"){
					showTenderBulletinDatas(data);
					shwoNumInfo(pageNo,count,"tenderBulletinShowNumBegin","tenderBulletinShowNumEnd");
					$("#tenderBulletinTotalNumShow").text(count);
				}else if(businessType =="开标记录"){
					showOpenBidRecordDatas(data);
					shwoNumInfo(pageNo,count,"bidOpenShowNumBegin","bidOpenShowNumEnd");
					$("#openBidRecordTotalNumShow").text(count);
				}else if(businessType =="评标公示"){
					showBidEvaluationDatas(data);
					shwoNumInfo(pageNo,count,"bidEvaluationShowNumBegin","bidEvaluationShowNumEnd");
					$("#bidEvaluationTotalNumShow").text(count);
				}else if(businessType =="中标公告"){
					showWinBidBulletinDatas(data);
					shwoNumInfo(pageNo,count,"winBidShowNumBegin","winBidShowNumEnd");
					$("#winBidTotalNumShow").text(count);
				}/*else if(businessType =="招标项目"){
					showTenderProjectDatas(data);
					shwoNumInfo(pageNo,count,"tenderProjectShowNumBegin","tenderProjectShowNumEnd");
					$("#tenderProjectTotalNumShow").text(count);
				}*/
				fenye();
				$('#vaptcha-container').hide();
				if (vaptchaObj) vaptchaObj.reset();
			}else{
				console.log('服务器验证失败:', data.message);
				layer.alert('验证失败，请重试');
	            $('#vaptcha-container').hide();
	            if (vaptchaObj) vaptchaObj.reset();
			}
			
		},error:function(data){
			layer.alert('验证失败，请重试');
			$('#vaptcha-container').hide();
			if (vaptchaObj) vaptchaObj.reset();
		}
	});
}