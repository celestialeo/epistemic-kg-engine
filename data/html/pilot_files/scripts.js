var $ = jQuery.noConflict();
$(window).scroll(function(){
    if ($(window).scrollTop() >= 230) {
        $("nav").addClass("fixednav");
        $(".wrap").addClass("innerfixed");
        $(".sidebar").addClass("innerfixed");
        $(".about-menu-class ul").addClass("fixedmenu");
        $(".create-menu-class ul").addClass("fixedmenu");
        $(".projects-menu-class ul").addClass("fixedmenu");
        $(".mooc-menu-class ul").addClass("fixedmenu");
        $(".resources-menu-class ul").addClass("fixedmenu");
    }
    else {
        $("nav").removeClass("fixednav");
        $(".wrap").removeClass("innerfixed");
        $(".sidebar").removeClass("innerfixed");
        $(".about-menu-class ul").removeClass("fixedmenu");
        $(".create-menu-class ul").removeClass("fixedmenu");
        $(".projects-menu-class ul").removeClass("fixedmenu");
        $(".mooc-menu-class ul").removeClass("fixedmenu");
        $(".resources-menu-class ul").removeClass("fixedmenu");
    }
});

$(document).ready(function (){
    
//    var offset = $(':target').offset();
//    var scrollto = offset.top - 60; // minus fixed header height
//    $('html, body').animate({scrollTop:scrollto}, 0);
    
    $('a[href^="#"]').on('click',function (e) {
            e.preventDefault();
 
            var target = this.hash,
            $target = $(target);
 
            $('html, body').stop().animate({
                'scrollTop': $target.offset().top
            }, 900, 'swing', function () {
                window.location.hash = target;
            });
        });
});